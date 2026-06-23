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

from ..geo import Affine, GeoInfo, resolve_geo
from loguru import logger as log
from ..logging_setup import log_distribution

# 树高合理上限(m)。
_MAX_PLAUSIBLE_HEIGHT = 120.0
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
        log.info("[fusion] rasterio 载入单波段: {} 尺寸={}", path, (arr.shape[1], arr.shape[0]))
        return arr, geo
    except ImportError:
        pass
    except Exception as e:  # 损坏/不支持 -> 回退 Pillow
        log.warning("[fusion] rasterio 读取失败,回退 Pillow: {} ({})", path, e)
    from PIL import Image

    with Image.open(path) as im:
        arr = np.asarray(im.convert("F"), dtype="float32")
    log.warning(
        "[fusion] 未装 rasterio,Pillow 整图载入单波段: {} 尺寸={}",
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
        log.error("[fusion] 缺少点云处理依赖库，请安装 (pip install laspy scipy): {}", e)
        raise e

    log.info("[fusion] 开始解析点云: {} 网格大小={:.3f}m", las_path, grid_size)
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
        log.warning("[fusion] 地面点比例低({:.2f}%)或少于100个，启动形态学局部最低点地面拟合", 100.0 * n_ground / max(n_total, 1))
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
    log.info("[fusion] 构建地面点树以计算局部 DEM (地面点数={})", len(ground_z))
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

    # 基于点云自身地理包围盒创建网格，由 CHMSampler 的仿射变换自动完成空间跨分辨率对齐。
    x_min, x_max = np.min(x), np.max(x)
    y_min, y_max = np.min(y), np.max(y)
    
    cols = max(1, int(np.ceil((x_max - x_min) / grid_size)))
    rows = max(1, int(np.ceil((y_max - y_min) / grid_size)))
    
    col_idx = ((x - x_min) / grid_size).astype(np.int32)
    row_idx = ((y_max - y) / grid_size).astype(np.int32)
    
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
    new_transform = Affine(grid_size, 0.0, x_min, 0.0, -grid_size, y_max)
    # EPSG 可从 las 中提取，若未提供使用 EPSG:4326
    epsg = 4326
    try:
        if las.header.parse_crs() is not None:
            epsg_str = las.header.parse_crs().to_epsg()
            if epsg_str:
                epsg = int(epsg_str)
    except Exception:
        pass
    
    # 判定坐标系种类
    crs_kind = "unknown"
    origin_lat = None
    if epsg == 4326:
        crs_kind = "geographic"
        origin_lat = float(y_max + y_min) / 2.0
    else:
        crs_kind = "projected"

    geo_info = GeoInfo(
        transform=new_transform,
        crs_kind=crs_kind,
        origin_lat=origin_lat,
        source="las_mesh",
    )
    log.info("[fusion] 点云网格化成功: CHM 尺寸=%dx%d 范围=[{:.2f}, {:.2f}]m", cols, rows, float(np.nanmin(chm)), float(np.nanmax(chm)))
    return chm, geo_info, (x, y, height_above_ground)


@dataclass
class CHMSampler:
    """在 RGB 检测框上采样 CHM 树高和树冠体积。支持仿射跨分辨率投影对齐。"""

    chm: np.ndarray
    chm_transform: Optional[Affine] = None
    rgb_transform: Optional[Affine] = None
    stat: str = "max"
    max_height: float = _MAX_PLAUSIBLE_HEIGHT
    source_name: str = "chm"
    volume_method: str = "cbh"
    cbh_factor: float = 0.3
    voxel_size: float = 0.2
    raw_points: Optional[tuple[np.ndarray, np.ndarray, np.ndarray]] = None
    las_grid_size: float = 0.05
    
    def __post_init__(self) -> None:
        if self.stat not in _VALID_STATS:
            log.warning("[fusion] 未知统计量 {},回退 max", self.stat)
            self.stat = "max"
        if self.volume_method not in _VALID_VOLUME_METHODS:
            log.warning("[fusion] 未知体积估算方法 {}, 回退 cbh", self.volume_method)
            self.volume_method = "cbh"
        coreg = self.chm_transform is not None and self.rgb_transform is not None
        mode = "仿射配准" if coreg else "像素对齐"
        log.info(
            "CHMSampler 初始化: CHM 尺寸=%dx%d 配准模式=%s 统计量=%s 体积估算=%s (factor=%.2f)",
            self.chm.shape[1], self.chm.shape[0], mode, self.stat, self.volume_method, self.cbh_factor
        )

    @property
    def coregistered(self) -> bool:
        return self.chm_transform is not None and self.rgb_transform is not None

    def metrics_for_detection(self, det) -> tuple[Optional[float], Optional[float], str]:
        """计算检测框对应的树高与树冠体积。

        将检测框在影像中的完整包围盒区域映射到 CHM 网格中，
        并在该包围盒切片内寻找树高估计（默认为 Max）并计算体积地学积分。
        """
        wx_min = wx_max = wy_min = wy_max = 0.0
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
            return None, None, "chm_out_of_bounds"

        win = self.chm[r0:r1, c0:c1]
        valid_h = win[~np.isnan(win)]
        if valid_h.size == 0:
            return None, None, "chm_nodata"

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
            return None, None, "chm_outlier"

        # 2. 树冠三维体积估算
        if self.coregistered:
            pixel_area = abs(self.chm_transform.pixel_size_x() * self.chm_transform.pixel_size_y())
        else:
            # 若无地理参考，设定单像素面积为 1m2 作为占位
            pixel_area = 1.0

        # 计算树冠宽度和高度的地理单位长度
        if self.coregistered:
            wx1, wy1 = self.rgb_transform.pixel_to_world(det.x1, det.y1)
            wx2, wy2 = self.rgb_transform.pixel_to_world(det.x2, det.y2)
            w_geo = abs(wx2 - wx1)
            h_geo = abs(wy2 - wy1)
        else:
            w_geo = det.width
            h_geo = det.height
        r = (w_geo + h_geo) / 4.0  # 树冠平均半径
        
        cbh = h_est * self.cbh_factor
        h_crown = max(0.0, h_est - cbh)

        actual_method = self.volume_method
        if actual_method in ("convex_hull", "voxel") and self.raw_points is None:
            log.warning(
                "[fusion] 检测到体积估算方法为 {}, 但未提供点云数据，回退到 A-1 (cbh) 枝下高积分法",
                actual_method
            )
            actual_method = "cbh"

        volume = 0.0
        if actual_method == "column":
            forest_h = valid_h[valid_h >= 0.5]
            if forest_h.size > 0:
                volume = float(np.sum(forest_h) * pixel_area)
        elif actual_method == "cbh":
            crown_pixels = valid_h[valid_h >= cbh]
            if crown_pixels.size > 0:
                volume = float(np.sum(crown_pixels - cbh) * pixel_area)
        elif actual_method == "paraboloid":
            volume = float(0.5 * np.pi * (r ** 2) * h_crown)
        elif actual_method == "cone":
            volume = float((1.0 / 3.0) * np.pi * (r ** 2) * h_crown)
        elif actual_method == "ellipsoid":
            volume = float((2.0 / 3.0) * np.pi * (r ** 2) * h_crown)
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
                    volume = float(hull.volume)
                except Exception as e:
                    log.warning("[fusion] 凸包体积计算失败(可能是点共面)，回退至 cbh 积分: {}", e)
                    crown_pixels = valid_h[valid_h >= cbh]
                    if crown_pixels.size > 0:
                        volume = float(np.sum(crown_pixels - cbh) * pixel_area)
            else:
                log.warning("[fusion] 边界内有效点数少于4个(实际为 {})，回退至 cbh 积分", len(tx))
                crown_pixels = valid_h[valid_h >= cbh]
                if crown_pixels.size > 0:
                    volume = float(np.sum(crown_pixels - cbh) * pixel_area)
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
                volume = float(len(unique_voxels) * (vs ** 3))
            else:
                crown_pixels = valid_h[valid_h >= cbh]
                if crown_pixels.size > 0:
                    volume = float(np.sum(crown_pixels - cbh) * pixel_area)

        return h_est, volume, self.source_name

    def height_for_detection(self, det) -> tuple[Optional[float], str]:
        """保持原有 height 接口，向后兼容。"""
        h, _, src = self.metrics_for_detection(det)
        return h, src

    def annotate(self, detections) -> dict:
        """为每个检测写入 extra 物理指标，返回统计摘要。"""
        n_h = n_nod = n_out = n_unreg = 0
        heights: list[float] = []
        volumes: list[float] = []
        for d in detections:
            h, vol, src = self.metrics_for_detection(d)
            if not hasattr(d, "extra") or d.extra is None:
                continue
            d.extra["height"] = h
            d.extra["height_source"] = src
            d.extra["volume"] = vol
            if src == "chm":
                n_h += 1
                if h is not None:
                    heights.append(h)
                if vol is not None:
                    volumes.append(vol)
            elif src == "chm_nodata":
                n_nod += 1
            elif src == "chm_outlier":
                n_out += 1
            else:
                n_unreg += 1
        log.info(
            "[fusion] 树高与体积标注: 成功={} nodata={} 超限={} 未配准={}",
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
            if dsm.shape != dem.shape:
                log.info("[fusion] DSM/DEM 尺寸不一致 ({} vs {})，正在尝试重采样对齐...", dsm.shape, dem.shape)
                try:
                    import rasterio
                    from rasterio.warp import reproject, Resampling
                    dem_resampled = np.full_like(dsm, np.nan, dtype="float32")
                    with rasterio.open(dsm_path) as src_dsm, rasterio.open(dem_path) as src_dem:
                        reproject(
                             source=rasterio.band(src_dem, 1),
                             destination=dem_resampled,
                             src_transform=src_dem.transform,
                             src_crs=src_dem.crs,
                             dst_transform=src_dsm.transform,
                             dst_crs=src_dsm.crs,
                             resampling=Resampling.bilinear,
                             src_nodata=src_dem.nodata,
                             dst_nodata=np.nan,
                        )
                    dem = dem_resampled
                    dem_geo = dsm_geo
                    log.info("[fusion] DSM/DEM 成功通过重投影对齐。")
                except Exception as e:
                    log.warning("[fusion] 尝试重采样 DEM 对齐 DSM 失败: {}", e)
                    return None
            chm = chm_from_dsm_dem(dsm, dem)
            chm_geo = dsm_geo or dem_geo
            source_name = "dsm_dem"
        else:
            # 单独 DSM 渠道，使用常量 dem_default_value (默认 0.0m)
            log.info("[fusion] 单独 DSM 模式，使用背景 DEM 常数背景高程: {}m", dem_default_value)
            dem = np.full_like(dsm, dem_default_value, dtype="float32")
            chm = chm_from_dsm_dem(dsm, dem)
            chm_geo = dsm_geo
            source_name = "dsm_only"
    else:
        return None

    if chm is None:
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
        stat=stat,
        source_name=source_name,
        volume_method=volume_method,
        cbh_factor=cbh_factor,
        voxel_size=voxel_size,
        raw_points=raw_pts,
        las_grid_size=las_grid_size,
    )
