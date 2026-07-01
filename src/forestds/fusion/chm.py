"""CHM 树高与树冠体积提取。

职责：
  - CHM = DSM − DEM（nodata→NaN，负值裁 0）；
  - 支持多渠道源输入（CHM, DSM+DEM, 单独DSM, 点云LAS）；
  - 将检测框映射到 CHM 地理范围包围盒内，计算树高（Max/p95）与树冠体积地学积分。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..geo import Affine, GeoInfo, resolve_geo, _M_PER_DEG_LAT
from loguru import logger as log
from ..logging_setup import log_distribution

# 树高合理上限(m)。
_MAX_PLAUSIBLE_HEIGHT = 50.0
_VALID_STATS = ("p95", "max", "median", "mean")
_VALID_VOLUME_METHODS = ("cbh", "paraboloid", "cone", "ellipsoid", "column")


def tree_height_from_chm(dsm: float, dem: float) -> float:
    """标量树高 = DSM - DEM(负值裁 0)。纯函数,便于单测。"""
    return max(0.0, float(dsm) - float(dem))


def chm_from_dsm_dem(
    dsm,
    dem,
    *,
    dsm_nodata: Optional[float] = None,
    dem_nodata: Optional[float] = None,
    clip_negative: bool = True,
) -> np.ndarray:
    """由 DSM/DEM 阵列算 CHM。nodata→NaN,负值（可选）裁 0,返回 float32。"""
    dsm = np.asarray(dsm, dtype="float32").copy()
    dem = np.asarray(dem, dtype="float32").copy()
    if dsm.shape != dem.shape:
        raise ValueError(f"DSM/DEM 尺寸不一致: {dsm.shape} vs {dem.shape}")
    if dsm_nodata is not None:
        dsm[dsm == np.float32(dsm_nodata)] = np.nan
    if dem_nodata is not None:
        dem[dem == np.float32(dem_nodata)] = np.nan
    chm = dsm - dem
    if clip_negative:
        with np.errstate(invalid="ignore"):
            chm = np.where(np.isnan(chm), np.nan, np.maximum(chm, 0.0))
    return chm.astype("float32")


def load_single_band(path: str):
    """载入单波段栅格为 float32 阵列 + GeoInfo|None。rasterio 优先，否则 Pillow。"""
    try:
        import rasterio  # type: ignore

        with rasterio.open(path) as ds:
            arr = ds.read(1).astype("float32")
            nod = ds.nodata
            if nod is not None:
                arr = np.where(arr == np.float32(nod), np.nan, arr).astype("float32")
            geo = resolve_geo(path, transform=ds.transform, crs=ds.crs)
        log.info("rasterio 载入单波段: {} 尺寸={}", path, (arr.shape[1], arr.shape[0]))
        return arr, geo
    except ImportError:
        pass
    except Exception as e:  # 损坏/不支持 -> 回退 Pillow
        log.warning("rasterio 读取失败,回退 Pillow: {} ({})", path, e)
    from PIL import Image

    with Image.open(path) as im:
        arr = np.asarray(im.convert("F"), dtype="float32")
    log.warning(
        "未装 rasterio,Pillow 整图载入单波段: {} 尺寸={}",
        path, (arr.shape[1], arr.shape[0]),
    )
    geo = resolve_geo(path)
    return arr, geo


def chm_from_las(
    las_path: str,
    grid_size: float = 0.05,
    rgb_geo: Optional[GeoInfo] = None,
) -> tuple[np.ndarray, Optional[GeoInfo], Optional[tuple[np.ndarray, np.ndarray, np.ndarray]]]:
    """读取 LAS 点云，进行高度归一化并格网化，生成 CHM 矩阵与 GeoInfo。

    利用地面点(Class 2)估计背景DEM，并计算非地面点的高度。支持未分类点云自动退级。
    """
    try:
        import laspy
        from scipy.spatial import cKDTree
    except ImportError as e:
        log.error("缺少点云处理依赖库，请安装 (pip install laspy scipy): {}", e)
        raise e

    log.info("开始解析点云: {} 网格大小={:.3f}m", las_path, grid_size)
    with laspy.open(las_path) as fh:
        las = fh.read()
    
    x = np.asarray(las.x, dtype="float64")
    y = np.asarray(las.y, dtype="float64")
    z = np.asarray(las.z, dtype="float32")
    
    # 提取分类，若无则默认全 1 (未分类)
    try:
        classification = np.asarray(las.classification, dtype="uint8")
    except Exception:
        classification = np.ones(len(z), dtype="uint8")

    # 1. 识别地面点与树冠点
    ground_mask = (classification == 2)
    n_ground = int(np.sum(ground_mask))
    n_total = len(z)

    # 自动退级：如果地面点极少(比如未分类或分类缺失)，采用 5m 网格局部最小值估计地面
    if n_ground < n_total * 0.05 or n_ground < 100:
        log.warning("地面点比例低({:.2f}%)或少于100个，启动形态学局部最低点地面拟合", 100.0 * n_ground / max(n_total, 1))
        # 5m 的格网尺寸来划分估算地面
        coarse_sz = 5.0
        x_min, x_max = np.min(x), np.max(x)
        y_min, y_max = np.min(y), np.max(y)
        c_cols = max(1, int(np.ceil((x_max - x_min) / coarse_sz)))
        c_rows = max(1, int(np.ceil((y_max - y_min) / coarse_sz)))
        c_col_idx = np.clip(((x - x_min) / coarse_sz).astype(np.int32), 0, c_cols - 1)
        c_row_idx = np.clip(((y_max - y) / coarse_sz).astype(np.int32), 0, c_rows - 1)
        c_flat = c_row_idx * c_cols + c_col_idx
        
        # 寻找每个粗格网的最低高程值
        min_z_grid = np.full(c_rows * c_cols, np.inf, dtype=np.float32)
        np.minimum.at(min_z_grid, c_flat, z)
        
        # 构建虚拟地面点集合
        valid_indices = np.where(min_z_grid != np.inf)[0]
        v_rows = valid_indices // c_cols
        v_cols = valid_indices % c_cols
        # 每个格网中心地理坐标
        v_x = x_min + (v_cols + 0.5) * coarse_sz
        v_y = y_max - (v_rows + 0.5) * coarse_sz
        v_z = min_z_grid[valid_indices]
        
        ground_coords = np.column_stack((v_x, v_y))
        ground_z = v_z
    else:
        ground_coords = np.column_stack((x[ground_mask], y[ground_mask]))
        ground_z = z[ground_mask]

    # 2. 地面高程插值与归一化
    log.info("构建地面点树以计算局部 DEM (地面点数={})", len(ground_z))
    tree = cKDTree(ground_coords)
    # 每个点找最近 of 3 个地面点，以反距离权重插值计算基底高程
    dists, indices = tree.query(np.column_stack((x, y)), k=min(3, len(ground_z)))
    if dists.ndim == 1:  # 只有一个地面点的情况
        z_base = ground_z[indices]
    else:
        weights = 1.0 / np.maximum(dists, 1e-6)
        w_sum = np.sum(weights, axis=1, keepdims=True)
        z_base = np.sum(ground_z[indices] * (weights / w_sum), axis=1)

    # 相对高度
    height_above_ground = z - z_base
    height_above_ground = np.maximum(0.0, height_above_ground)

    # 3. 判定坐标系种类与网格分辨率换算
    epsg = 4326
    try:
        if las.header.parse_crs() is not None:
            epsg_str = las.header.parse_crs().to_epsg()
            if epsg_str:
                epsg = int(epsg_str)
    except Exception:
        pass
    
    x_min, x_max = np.min(x), np.max(x)
    y_min, y_max = np.min(y), np.max(y)
    
    crs_kind = "unknown"
    origin_lat = None
    import math
    if epsg == 4326:
        crs_kind = "geographic"
        origin_lat = float(y_max + y_min) / 2.0
        grid_size_x = grid_size / (_M_PER_DEG_LAT * math.cos(math.radians(origin_lat)))
        grid_size_y = grid_size / _M_PER_DEG_LAT
    else:
        crs_kind = "projected"
        grid_size_x = grid_size
        grid_size_y = grid_size

    cols = max(1, int(np.ceil((x_max - x_min) / grid_size_x)))
    rows = max(1, int(np.ceil((y_max - y_min) / grid_size_y)))
    
    col_idx = ((x - x_min) / grid_size_x).astype(np.int32)
    row_idx = ((y_max - y) / grid_size_y).astype(np.int32)
    
    # 滤除越界点
    valid_mask = (col_idx >= 0) & (col_idx < cols) & (row_idx >= 0) & (row_idx < rows)
    col_idx = col_idx[valid_mask]
    row_idx = row_idx[valid_mask]
    h_vals = height_above_ground[valid_mask]
    
    # 极速向量化 2D 网格求最大值
    chm_flat = np.zeros(rows * cols, dtype=np.float32)
    flat_idx = row_idx * cols + col_idx
    np.maximum.at(chm_flat, flat_idx, h_vals)
    chm = chm_flat.reshape((rows, cols))
    
    # 无点覆盖的区域设为 NaN
    has_points = np.zeros(rows * cols, dtype=bool)
    has_points[flat_idx] = True
    chm[~has_points.reshape((rows, cols))] = np.nan
    
    # 构造仿射地理转换信息
    from ..geo import Affine
    new_transform = Affine(grid_size_x, 0.0, x_min, 0.0, -grid_size_y, y_max)
    
    geo_info = GeoInfo(
        transform=new_transform,
        crs_kind=crs_kind,
        origin_lat=origin_lat,
        source="las_mesh",
    )
    log.info("点云网格化成功: CHM 尺寸={}x{} 范围=[{:.2f}, {:.2f}]m", cols, rows, float(np.nanmin(chm[~np.isnan(chm)])), float(np.nanmax(chm[~np.isnan(chm)])))
    return chm, geo_info, (x, y, height_above_ground)


@dataclass
class CHMSampler:
    """在 RGB 检测框上采样 CHM 树高和树冠体积。支持仿射跨分辨率投影对齐。"""

    chm: np.ndarray
    chm_transform: Optional[Affine] = None
    rgb_transform: Optional[Affine] = None
    chm_geo: Optional[GeoInfo] = None
    rgb_geo: Optional[GeoInfo] = None
    stat: str = "max"
    max_height: float = _MAX_PLAUSIBLE_HEIGHT
    source_name: str = "chm"
    volume_method: str = "cbh"
    cbh_factor: float = 0.3
    voxel_size: float = 0.2
    raw_points: Optional[tuple[np.ndarray, np.ndarray, np.ndarray]] = None
    las_grid_size: float = 0.05
    dsm: Optional[np.ndarray] = None
    dem: Optional[np.ndarray] = None
    dem_geo: Optional[GeoInfo] = None
    chm_threshold: float = 0.1
    find_real_canopy: bool = True
    max_valid_height: float = 8.0
    
    def __post_init__(self) -> None:
        if self.stat not in _VALID_STATS:
            log.warning("未知统计量 {},回退 max", self.stat)
            self.stat = "max"
        if self.volume_method not in _VALID_VOLUME_METHODS:
            log.warning("未知体积估算方法 {}, 回退 cbh", self.volume_method)
            self.volume_method = "cbh"
            
        if self.chm is not None:
            self.chm = np.minimum(self.chm, self.max_valid_height)
            
        if self.source_name == "dsm_dem" and self.dsm is not None:
            shape_h, shape_w = self.dsm.shape
        else:
            shape_h, shape_w = self.chm.shape
            
        coreg = self.chm_transform is not None and self.rgb_transform is not None
        mode = "仿射配准" if coreg else "像素对齐"
        log.info(
            "CHMSampler 初始化: CHM 尺寸={}x{} 配准模式={} 统计量={} 体积估算={} (factor={:.2f}) find_real_canopy={} max_valid_height={}m",
            shape_w, shape_h, mode, self.stat, self.volume_method, self.cbh_factor, self.find_real_canopy, self.max_valid_height
        )

    @property
    def coregistered(self) -> bool:
        return self.chm_transform is not None and self.rgb_transform is not None

    def metrics_for_detection(self, det) -> dict:
        """计算检测框对应的树高与树冠体积。

        将检测框在影像中的完整包围盒区域映射到 CHM 网格中，
        并在该包围盒切片内寻找树高估计（默认为 Max）并计算体积地学积分。
        """
        wx_min = wx_max = wy_min = wy_max = 0.0
        
        if self.source_name == "dsm_dem" and self.dsm is not None and self.dem is not None:
            if not self.coregistered:
                # 像素对齐
                h_h, h_w = self.dsm.shape
                c0 = max(0, int(round(det.x1)))
                c1 = min(h_w, int(round(det.x2)) + 1)
                r0 = max(0, int(round(det.y1)))
                r1 = min(h_h, int(round(det.y2)) + 1)
                
                win_dsm = self.dsm[r0:r1, c0:c1]
                if win_dsm.size == 0:
                    return {"error": "chm_out_of_bounds"}
                win_dem = self.dem[r0:r1, c0:c1]
                if win_dem.shape != win_dsm.shape:
                    win_dem = win_dem[:win_dsm.shape[0], :win_dsm.shape[1]]
            else:
                # 仿射配准对齐
                h_h, h_w = self.dsm.shape
                wx1, wy1 = self.rgb_transform.pixel_to_world(det.x1, det.y1)
                wx2, wy2 = self.rgb_transform.pixel_to_world(det.x2, det.y2)
                wx_min, wx_max = min(wx1, wx2), max(wx1, wx2)
                wy_min, wy_max = min(wy1, wy2), max(wy1, wy2)
                
                col1, row1 = self.chm_transform.world_to_pixel(wx_min, wy_max)
                col2, row2 = self.chm_transform.world_to_pixel(wx_max, wy_min)
                
                c0 = max(0, int(round(min(col1, col2))))
                c1 = min(h_w, int(round(max(col1, col2))) + 1)
                r0 = max(0, int(round(min(row1, row2))))
                r1 = min(h_h, int(round(max(row1, row2))) + 1)
                
                win_dsm = self.dsm[r0:r1, c0:c1]
                if win_dsm.size == 0:
                    return {"error": "chm_out_of_bounds"}
                
                dem_transform = self.dem_geo.transform if self.dem_geo is not None else self.chm_transform
                dem_h, dem_w = self.dem.shape
                
                d_col1, d_row1 = dem_transform.world_to_pixel(wx_min, wy_max)
                d_col2, d_row2 = dem_transform.world_to_pixel(wx_max, wy_min)
                
                dc0 = max(0, int(round(min(d_col1, d_col2))))
                dc1 = min(dem_w, int(round(max(d_col1, d_col2))) + 1)
                dr0 = max(0, int(round(min(d_row1, d_row2))))
                dr1 = min(dem_h, int(round(max(d_row1, d_row2))) + 1)
                
                win_dem_raw = self.dem[dr0:dr1, dc0:dc1]
                if win_dem_raw.size == 0:
                    return {"error": "chm_nodata"}
                
                # 局部双线性缩放
                try:
                    from scipy.ndimage import zoom
                    zoom_y = win_dsm.shape[0] / win_dem_raw.shape[0]
                    zoom_x = win_dsm.shape[1] / win_dem_raw.shape[1]
                    win_dem = zoom(win_dem_raw, (zoom_y, zoom_x), order=1)
                    if win_dem.shape != win_dsm.shape:
                        win_dem = win_dem[:win_dsm.shape[0], :win_dsm.shape[1]]
                        if win_dem.shape != win_dsm.shape:
                            tmp = np.full_like(win_dsm, np.nan)
                            tmp[:win_dem.shape[0], :win_dem.shape[1]] = win_dem
                            win_dem = tmp
                except Exception:
                    win_dem = np.full_like(win_dsm, np.nanmedian(win_dem_raw))
            
            win = win_dsm - win_dem
            win = np.where(np.isnan(win), np.nan, np.maximum(win, 0.0))
        else:
            if not self.coregistered:
                # 无仿射信息：假设 1:1 像素对齐
                h_h, h_w = self.chm.shape
                c0 = max(0, int(round(det.x1)))
                c1 = min(h_w, int(round(det.x2)) + 1)
                r0 = max(0, int(round(det.y1)))
                r1 = min(h_h, int(round(det.y2)) + 1)
            else:
                h_h, h_w = self.chm.shape
                # 投影检测框的 4 个地理边界点，取包围盒
                wx1, wy1 = self.rgb_transform.pixel_to_world(det.x1, det.y1)
                wx2, wy2 = self.rgb_transform.pixel_to_world(det.x2, det.y2)
                
                # 由于 Y 轴方向，做 min/max 鲁棒处理
                wx_min, wx_max = min(wx1, wx2), max(wx1, wx2)
                wy_min, wy_max = min(wy1, wy2), max(wy1, wy2)
                
                # 将地理包围盒转回 CHM 的像素格网坐标
                col1, row1 = self.chm_transform.world_to_pixel(wx_min, wy_max)
                col2, row2 = self.chm_transform.world_to_pixel(wx_max, wy_min)
                
                c0 = max(0, int(round(min(col1, col2))))
                c1 = min(h_w, int(round(max(col1, col2))) + 1)
                r0 = max(0, int(round(min(row1, row2))))
                r1 = min(h_h, int(round(max(row1, row2))) + 1)

            if c0 >= c1 or r0 >= r1:
                return {"error": "chm_out_of_bounds"}

            win = self.chm[r0:r1, c0:c1]

        # 计算单个像元地理面积
        if self.chm_geo is not None:
            pixel_area = self.chm_geo.pixel_area_m2() or 1.0
        else:
            if self.coregistered:
                pixel_area = abs(self.chm_transform.pixel_size_x() * self.chm_transform.pixel_size_y())
            else:
                pixel_area = 1.0

        # ── 提取高度指标并计算有效高度像元 ─────────────────────────────────────
        valid_h = win[~np.isnan(win) & (win >= self.chm_threshold)]
        if valid_h.size == 0:
            return {"error": "chm_nodata"}

        # 1. 树高提取
        if self.stat == "max":
            h_est = float(np.max(valid_h))
        elif self.stat == "median":
            h_est = float(np.median(valid_h))
        elif self.stat == "mean":
            h_est = float(np.mean(valid_h))
        else:
            h_est = float(np.percentile(valid_h, 95))

        if h_est < 0.0 or h_est > self.max_height:
            return {"error": "chm_outlier"}

        # 2. 树冠三维体积估算

        # 计算树冠宽度和高度的地理单位长度
        if self.coregistered:
            wx1, wy1 = self.rgb_transform.pixel_to_world(det.x1, det.y1)
            wx2, wy2 = self.rgb_transform.pixel_to_world(det.x2, det.y2)
            w_geo = abs(wx2 - wx1)
            h_geo = abs(wy2 - wy1)
            
            # 如果是地理坐标系，将经纬度跨度换算为米制单位
            if self.rgb_geo is not None and self.rgb_geo.crs_kind == "geographic":
                lat = self.rgb_geo.origin_lat or 0.0
                from ..geo import _M_PER_DEG_LAT
                import math
                m_per_deg_lon = _M_PER_DEG_LAT * math.cos(math.radians(lat))
                w_geo = w_geo * m_per_deg_lon
                h_geo = h_geo * _M_PER_DEG_LAT
        else:
            w_geo = det.width
            h_geo = det.height
            
        r_est = (w_geo + h_geo) / 4.0  # 树冠估算平均半径
        
        cbh = h_est * self.cbh_factor
        h_crown = max(0.0, h_est - cbh)

        # A. 估计轨 (est track)
        area_px_est = float(det.width * det.height)
        if self.rgb_geo is not None:
            area_geo_est = w_geo * h_geo
        else:
            area_geo_est = area_px_est * pixel_area
        vol_est = float((1.0 / 3.0) * np.pi * (r_est ** 2) * h_crown)

        # B. 真实轨 (real track)
        if self.find_real_canopy:
            area_px_real = float(valid_h.size)
            area_geo_real = float(valid_h.size * pixel_area)
            
            import math
            r_real = math.sqrt(area_geo_real / np.pi) if area_geo_real > 0 else 0.0
            
            actual_method = self.volume_method
            if actual_method in ("convex_hull", "voxel") and self.raw_points is None:
                log.warning(
                    "检测到体积估算方法为 {}, 但未提供点云数据，回退到 A-1 (cbh) 枝下高积分法",
                    actual_method
                )
                actual_method = "cbh"

            vol_real = 0.0
            if actual_method == "column":
                forest_h = valid_h[valid_h >= 0.5]
                if forest_h.size > 0:
                    vol_real = float(np.sum(forest_h) * pixel_area)
            elif actual_method == "cbh":
                crown_pixels = valid_h[valid_h >= cbh]
                if crown_pixels.size > 0:
                    vol_real = float(np.sum(crown_pixels - cbh) * pixel_area)
            elif actual_method == "paraboloid":
                vol_real = float(0.5 * np.pi * (r_real ** 2) * h_crown)
            elif actual_method == "cone":
                vol_real = float((1.0 / 3.0) * np.pi * (r_real ** 2) * h_crown)
            elif actual_method == "ellipsoid":
                vol_real = float((2.0 / 3.0) * np.pi * (r_real ** 2) * h_crown)
            elif actual_method == "convex_hull":
                x_pts, y_pts, h_pts = self.raw_points
                mask = (x_pts >= wx_min) & (x_pts <= wx_max) & (y_pts >= wy_min) & (y_pts <= wy_max)
                tree_mask = mask & (h_pts >= cbh) & (h_pts <= self.max_height)
                tx = x_pts[tree_mask]
                ty = y_pts[tree_mask]
                th = h_pts[tree_mask]
                if len(tx) >= 4:
                    try:
                        from scipy.spatial import ConvexHull
                        pts_3d = np.column_stack((tx, ty, th))
                        hull = ConvexHull(pts_3d)
                        vol_real = float(hull.volume)
                    except Exception as e:
                        log.warning("凸包体积计算失败(可能是点共面)，回退至 cbh 积分: {}", e)
                        crown_pixels = valid_h[valid_h >= cbh]
                        if crown_pixels.size > 0:
                            vol_real = float(np.sum(crown_pixels - cbh) * pixel_area)
                else:
                    log.warning("边界内有效点数少于4个(实际为 {})，回退至 cbh 积分", len(tx))
                    crown_pixels = valid_h[valid_h >= cbh]
                    if crown_pixels.size > 0:
                        vol_real = float(np.sum(crown_pixels - cbh) * pixel_area)
            elif actual_method == "voxel":
                x_pts, y_pts, h_pts = self.raw_points
                mask = (x_pts >= wx_min) & (x_pts <= wx_max) & (y_pts >= wy_min) & (y_pts <= wy_max)
                tree_mask = mask & (h_pts >= cbh) & (h_pts <= self.max_height)
                tx = x_pts[tree_mask]
                ty = y_pts[tree_mask]
                th = h_pts[tree_mask]
                if len(tx) > 0:
                    vs = self.voxel_size
                    vx = (tx / vs).astype(np.int32)
                    vy = (ty / vs).astype(np.int32)
                    vh = (th / vs).astype(np.int32)
                    unique_voxels = set(zip(vx, vy, vh))
                    vol_real = float(len(unique_voxels) * (vs ** 3))
                else:
                    crown_pixels = valid_h[valid_h >= cbh]
                    if crown_pixels.size > 0:
                        vol_real = float(np.sum(crown_pixels - cbh) * pixel_area)
        else:
            area_px_real = area_px_est
            area_geo_real = area_geo_est
            vol_real = vol_est

        return {
            "height": h_est,
            "volume_est": vol_est,
            "volume_real": vol_real,
            "crown_area_px_est": area_px_est,
            "crown_area_px_real": area_px_real,
            "crown_area_geo_est": area_geo_est,
            "crown_area_geo_real": area_geo_real,
            "source_name": self.source_name,
        }

    def height_for_detection(self, det) -> tuple[Optional[float], str]:
        """保持原有 height 接口，向后兼容。"""
        res = self.metrics_for_detection(det)
        if "error" in res:
            return None, res["error"]
        return res["height"], res["source_name"]

    def annotate(self, detections) -> dict:
        """为每个检测写入 extra 物理指标，返回统计摘要。"""
        n_h = n_nod = n_out = n_unreg = 0
        heights: list[float] = []
        volumes: list[float] = []
        for d in detections:
            res = self.metrics_for_detection(d)
            if not hasattr(d, "extra") or d.extra is None:
                continue
            if "error" in res:
                src = res["error"]
                d.extra["height"] = None
                d.extra["height_source"] = src
                d.extra["volume"] = None
                d.extra["crown_area_px_est"] = None
                d.extra["crown_area_px_real"] = None
                d.extra["crown_area_geo_est"] = None
                d.extra["crown_area_geo_real"] = None
                d.extra["volume_est"] = None
                d.extra["volume_real"] = None
                if src == "chm_nodata":
                    n_nod += 1
                elif src == "chm_outlier":
                    n_out += 1
                elif src == "chm_out_of_bounds":
                    n_unreg += 1
            else:
                n_h += 1
                src = res["source_name"]
                h = res["height"]
                vol = res["volume_real"]
                d.extra["height"] = h
                d.extra["height_source"] = src
                d.extra["volume"] = vol
                d.extra["crown_area_px_est"] = res["crown_area_px_est"]
                d.extra["crown_area_px_real"] = res["crown_area_px_real"]
                d.extra["crown_area_geo_est"] = res["crown_area_geo_est"]
                d.extra["crown_area_geo_real"] = res["crown_area_geo_real"]
                d.extra["volume_est"] = res["volume_est"]
                d.extra["volume_real"] = res["volume_real"]
                if h is not None:
                    heights.append(h)
                if vol is not None:
                    volumes.append(vol)
        log.info(
            "树高与体积标注: 成功={} nodata={} 超限={} 未配准={}",
            n_h, n_nod, n_out, n_unreg,
        )
        if heights:
            log_distribution(log, "树高", heights, unit="m")
        if volumes:
            log_distribution(log, "树冠体积", volumes, unit="m³")
        return {
            "n_with_height": n_h,
            "n_nodata": n_nod,
            "n_outlier": n_out,
            "n_unregistered": n_unreg,
        }


def build_chm_sampler(
    *,
    chm_path: Optional[str] = None,
    dsm_path: Optional[str] = None,
    dem_path: Optional[str] = None,
    las_path: Optional[str] = None,
    las_grid_size: float = 0.05,
    dem_default_value: float = 0.0,
    rgb_transform: Optional[Affine] = None,
    rgb_geo: Optional[GeoInfo] = None,
    stat: str = "max",
    volume_method: str = "cbh",
    cbh_factor: float = 0.3,
    voxel_size: float = 0.2,
    chm_threshold: float = 0.1,
    find_real_canopy: bool = True,
    max_valid_height: float = 8.0,
) -> Optional[CHMSampler]:
    """根据多渠道源输入（chm、dsm+dem、单独dsm、las点云）构建统一的 CHMSampler。"""
    chm: Optional[np.ndarray] = None
    chm_geo: Optional[GeoInfo] = None
    raw_pts: Optional[tuple[np.ndarray, np.ndarray, np.ndarray]] = None
    
    if chm_path:
        chm, chm_geo = load_single_band(chm_path)
        source_name = "chm"
    elif las_path:
        chm, chm_geo, raw_pts = chm_from_las(las_path, grid_size=las_grid_size, rgb_geo=rgb_geo)
        source_name = "las"
    elif dsm_path:
        dsm, dsm_geo = load_single_band(dsm_path)
        if dem_path:
            dem, dem_geo = load_single_band(dem_path)
            chm = np.array([])
            chm_geo = dsm_geo
            source_name = "dsm_dem"
        else:
            # 单独 DSM 渠道，使用常量 dem_default_value (默认 0.0m)
            log.info("单独 DSM 模式，使用背景 DEM 常数背景高程: {}m", dem_default_value)
            dem = np.full_like(dsm, dem_default_value, dtype="float32")
            chm = chm_from_dsm_dem(dsm, dem)
            chm_geo = dsm_geo
            source_name = "dsm_only"
    else:
        return None

    if source_name == "dsm_dem" and dsm_path and dem_path:
        log.info(
            "CHM 模式: 延迟局部计算。DSM 尺寸={}x{} DEM 尺寸={}x{}",
            dsm.shape[1], dsm.shape[0], dem.shape[1], dem.shape[0]
        )
        chm_transform = chm_geo.transform if chm_geo is not None else None
        return CHMSampler(
            chm=chm,
            chm_transform=chm_transform,
            rgb_transform=rgb_transform or (rgb_geo.transform if rgb_geo else None),
            chm_geo=chm_geo,
            rgb_geo=rgb_geo,
            stat=stat,
            source_name=source_name,
            volume_method=volume_method,
            cbh_factor=cbh_factor,
            voxel_size=voxel_size,
            raw_points=raw_pts,
            las_grid_size=las_grid_size,
            dsm=dsm,
            dem=dem,
            dem_geo=dem_geo,
            chm_threshold=chm_threshold,
            find_real_canopy=find_real_canopy,
            max_valid_height=max_valid_height,
        )

    if chm is None or chm.size == 0:
        return None

    finite = chm[~np.isnan(chm)]
    total = int(chm.size)
    valid = int(finite.size)
    lo = float(np.min(finite)) if finite.size else float("nan")
    hi = float(np.max(finite)) if finite.size else float("nan")
    log.info(
        "CHM 生成完毕: 尺寸={} 有效像元={}/{} ({:.1f}%) 高程范围=[{:.2f}, {:.2f}]m",
        (chm.shape[1], chm.shape[0]), valid, total, 100.0 * valid / max(total, 1), lo, hi,
    )
    chm_transform = chm_geo.transform if chm_geo is not None else None
    return CHMSampler(
        chm=chm,
        chm_transform=chm_transform,
        rgb_transform=rgb_transform or (rgb_geo.transform if rgb_geo else None),
        chm_geo=chm_geo,
        rgb_geo=rgb_geo,
        stat=stat,
        source_name=source_name,
        volume_method=volume_method,
        cbh_factor=cbh_factor,
        voxel_size=voxel_size,
        raw_points=raw_pts,
        las_grid_size=las_grid_size,
        chm_threshold=chm_threshold,
        find_real_canopy=find_real_canopy,
        max_valid_height=max_valid_height,
    )
