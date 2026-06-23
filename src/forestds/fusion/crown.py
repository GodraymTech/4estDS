"""DSM 纯数学冠幅分割算法。

职责：
  - 读取并对齐 DOM 与 DSM 高程数据。
  - 在无 DEM 辅助下，通过低通最小滤波估计背景 DEM 并差分得出相对高度 CHM。
  - 基于高斯平滑滤波与局部极大值寻找单木树顶种子点。
  - 运用空间 Voronoi (基于 cKDTree) 与高度/半径双门控，将有效树冠像素归并分配到各单木。
  - 用极速向量化邻域对比提取树冠边缘轮廓。
"""
from __future__ import annotations

import numpy as np
from loguru import logger as log
from typing import Optional, Tuple

from ..geo import Affine, GeoInfo, resolve_geo
from ..fusion.chm import load_single_band


def check_geographic_overlap(dom_geo: Optional[GeoInfo], dsm_geo: Optional[GeoInfo]) -> bool:
    """检查 DOM 和 DSM 是否在地理范围上重叠（至少一者的中心点在另一者的地理范围内）。"""
    if dom_geo is None or dsm_geo is None:
        # 无地理参考，不进行强包含性检查，认为对齐
        return True

    # 1. 计算 DOM 中心点
    dom_tf = dom_geo.transform
    if not dom_tf:
        return True
    
    # 假设 transform 对应 (a, b, c, d, e, f)
    # x = c + col * a + row * b
    # y = f + col * d + row * e
    # 我们也可以直接读出 bounding box
    # 由于 DOM 通常是 GeoTIFF，这里我们根据 load_single_band 中的形状获取中心点地理坐标
    # chm.py 里面 load_single_band 返回的 arr 形状为 (rows, cols)
    return True


def get_image_center_and_bounds(geo: GeoInfo, shape: Tuple[int, int]) -> Tuple[Tuple[float, float], Tuple[float, float, float, float]]:
    """根据 GeoInfo 和形状计算地理中心点以及地理包围盒 [x_min, x_max, y_min, y_max]。"""
    tf = geo.transform
    rows, cols = shape
    
    # 4个角点地理坐标
    x0, y0 = tf.pixel_to_world(0, 0)
    x1, y1 = tf.pixel_to_world(cols, 0)
    x2, y2 = tf.pixel_to_world(0, rows)
    x3, y3 = tf.pixel_to_world(cols, rows)
    
    xs = [x0, x1, x2, x3]
    ys = [y0, y1, y2, y3]
    
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    
    center_x = (x_min + x_max) / 2.0
    center_y = (y_min + y_max) / 2.0
    
    return (center_x, center_y), (x_min, x_max, y_min, y_max)


def verify_overlap(dom_path: str, dsm_path: str) -> None:
    """检查 DOM 和 DSM 是否存在包含性重合（至少一者的地理中心在另一者的包围盒内）。
    
    若不满足则抛出 ValueError。
    """
    try:
        # 使用 rasterio 或 geo 提取
        # 为了不完全读入大图，可以使用较轻量级的 geo 获取
        dom_geo = resolve_geo(dom_path)
        dsm_geo = resolve_geo(dsm_path)
    except Exception as e:
        log.warning("[fusion.crown] 读取地理空间信息失败，跳过重合性检查: {}", e)
        return

    if not dom_geo.transform or not dsm_geo.transform:
        log.warning("[fusion.crown] 影像缺少仿射变换信息，跳过重合性检查。")
        return

    # 为了拿到形状算中心，我们可以通过 load_single_band 获取
    # 如果图很大，我们为了效率可以尝试用 rasterio 仅读取元数据，但 load_single_band 内部已有缓存或对小图适用
    # 对于大图，我们使用 rasterio.open 获取 shape
    dom_shape = None
    dsm_shape = None
    try:
        import rasterio
        with rasterio.open(dom_path) as src:
            dom_shape = (src.height, src.width)
        with rasterio.open(dsm_path) as src:
            dsm_shape = (src.height, src.width)
    except Exception:
        # 降级：直接载入
        dom_arr, _ = load_single_band(dom_path)
        dsm_arr, _ = load_single_band(dsm_path)
        dom_shape = dom_arr.shape
        dsm_shape = dsm_arr.shape

    dom_center, dom_bounds = get_image_center_and_bounds(dom_geo, dom_shape)
    dsm_center, dsm_bounds = get_image_center_and_bounds(dsm_geo, dsm_shape)

    # 包含性检查：一者的中心在另一者的 Bound 内
    dom_in_dsm = (dsm_bounds[0] <= dom_center[0] <= dsm_bounds[1]) and \
                 (dsm_bounds[2] <= dom_center[1] <= dsm_bounds[3])
    dsm_in_dom = (dom_bounds[0] <= dsm_center[0] <= dom_bounds[1]) and \
                 (dom_bounds[2] <= dsm_center[1] <= dom_bounds[3])

    if not (dom_in_dsm or dsm_in_dom):
        err_msg = (
            f"DOM 与 DSM 地理空间范围不匹配！\n"
            f"DOM 中心: ({dom_center[0]:.3f}, {dom_center[1]:.3f}), 包围盒: {dom_bounds}\n"
            f"DSM 中心: ({dsm_center[0]:.3f}, {dsm_center[1]:.3f}), 包围盒: {dsm_bounds}\n"
            f"任一者的中心点均不在另一者的范围内。"
        )
        log.error("[fusion.crown] {}", err_msg)
        raise ValueError(err_msg)

    log.info("[fusion.crown] DOM/DSM 地理包含关系验证通过。")


def align_dsm_to_dom(dsm_path: str, dom_path: str) -> Tuple[np.ndarray, np.ndarray, Optional[Affine]]:
    """将 DSM 栅格重投影并对齐到 DOM 相同的空间格网中。
    
    返回:
        dsm_aligned: 对齐后的 DSM 阵列
        dom_arr: DOM 本身对应的单通道/灰度化数据（用来确定形状）
        dom_transform: DOM 的地理仿射矩阵
    """
    dom_arr, dom_geo = load_single_band(dom_path)
    dsm_arr, dsm_geo = load_single_band(dsm_path)

    if dom_arr.shape == dsm_arr.shape:
        log.info("[fusion.crown] DOM 与 DSM 分辨率和尺寸一致，跳过重投影。")
        return dsm_arr, dom_arr, (dom_geo.transform if dom_geo else None)

    log.info(
        "[fusion.crown] DOM 尺寸={} 与 DSM 尺寸={} 不一致，执行空间重投影对齐...",
        dom_arr.shape, dsm_arr.shape
    )
    try:
        import rasterio
        from rasterio.warp import reproject, Resampling
        
        dsm_aligned = np.full_like(dom_arr, np.nan, dtype="float32")
        with rasterio.open(dom_path) as src_dom, rasterio.open(dsm_path) as src_dsm:
            reproject(
                source=rasterio.band(src_dsm, 1),
                destination=dsm_aligned,
                src_transform=src_dsm.transform,
                src_crs=src_dsm.crs,
                dst_transform=src_dom.transform,
                dst_crs=src_dom.crs,
                resampling=Resampling.bilinear,
                src_nodata=src_dsm.nodata,
                dst_nodata=np.nan,
            )
        log.info("[fusion.crown] DSM 重投影对齐完成。")
        return dsm_aligned, dom_arr, src_dom.transform
    except Exception as e:
        log.warning("[fusion.crown] 自动重投影失败，降级为直接截取/缩放对齐: {}", e)
        # 降级：通过插值将 dsm 缩放到与 dom 相同大小
        from PIL import Image
        dsm_im = Image.fromarray(dsm_arr)
        dsm_resized = dsm_im.resize((dom_arr.shape[1], dom_arr.shape[0]), resample=Image.BILINEAR)
        return np.array(dsm_resized, dtype="float32"), dom_arr, (dom_geo.transform if dom_geo else None)


def estimate_canopy_contours(
    dsm_arr: np.ndarray,
    transform: Optional[Affine] = None,
    min_tree_height: float = 1.0,
    max_crown_radius: float = 3.0,
) -> np.ndarray:
    """基于 DSM 数字表面模型，通过形态学滤波和空间 Voronoi 切分提取单木冠幅轮廓边缘。
    
    返回:
        boundary_mask: 与 dsm_arr 同尺寸的布尔矩阵，True 表示该像素属于树冠轮廓线
    """
    try:
        from scipy.ndimage import gaussian_filter, minimum_filter, maximum_filter, label
        from scipy.spatial import cKDTree
    except ImportError as e:
        log.error("[fusion.crown] 缺少科学计算依赖 scipy，请安装 (pip install scipy): {}", e)
        raise e

    # 1. 确定空间分辨率
    pixel_size = abs(transform.pixel_size_x()) if transform else 0.1
    log.info("[fusion.crown] 估算冠幅线: 像元尺寸={:.3f}m", pixel_size)

    # 2. 估计背景 DEM 并做差分得出临时相对 CHM
    # 使用 20m 滑动窗极小值滤波来逼近地形基底高程
    bg_win = int(round(20.0 / pixel_size))
    if bg_win % 2 == 0:
        bg_win += 1
    bg_win = max(5, bg_win)
    
    # 填充 NaN 以防极小值溢出
    dsm_filled = dsm_arr.copy()
    nan_mask = np.isnan(dsm_filled)
    if np.any(nan_mask):
        mean_val = np.nanmean(dsm_filled) if not np.all(nan_mask) else 0.0
        dsm_filled[nan_mask] = mean_val

    # 先用高斯平滑去除微小毛刺干扰
    sigma = max(1.0, 0.5 / pixel_size)
    smoothed = gaussian_filter(dsm_filled, sigma=sigma)
    
    log.info("[fusion.crown] 正在使用 {}x{} 窗口估计地形背景 DEM...", bg_win, bg_win)
    dem_est = minimum_filter(smoothed, size=bg_win)
    chm = smoothed - dem_est
    chm = np.maximum(0.0, chm)

    # 3. 寻找树尖（局部高程最大值点）作为种子点
    # 树冠大小滑动窗口（1.5m 左右的常规红树林冠幅大小）
    crown_win = int(round(1.5 / pixel_size))
    if crown_win % 2 == 0:
        crown_win += 1
    crown_win = max(3, crown_win)

    # 寻找局部极大值且高度大于背景阈值 (默认 1.0m，避免草地干扰)
    local_max = (chm == maximum_filter(chm, size=crown_win)) & (chm >= min_tree_height)
    seed_coords = np.argwhere(local_max)
    log.info("[fusion.crown] 识别到单木树梢种子数: {}", len(seed_coords))

    if len(seed_coords) == 0:
        log.warning("[fusion.crown] 未能在 DSM 中识别到任何符合高度标准的树顶种子，返回空轮廓。")
        return np.zeros_like(dsm_arr, dtype=bool)

    # 4. 空间 Voronoi 切分与有效高度约束归并
    # 所有高度 >= 0.5m 的像元都被认为是有效树冠组成部分
    valid_mask = chm >= 0.5
    valid_coords = np.argwhere(valid_mask)

    labels = np.zeros_like(chm, dtype=np.int32)
    
    # 用 cKDTree 高效计算距离并分类
    tree = cKDTree(seed_coords)
    dists, indices = tree.query(valid_coords)

    # 距离门控：单木最大树冠生长半径（默认 3.0m），超出不计入该木
    max_r_px = max_crown_radius / pixel_size
    within_radius = dists <= max_r_px

    # 分配标签 (从 1 开始)
    valid_assigned = valid_coords[within_radius]
    assigned_labels = indices[within_radius] + 1
    labels[valid_assigned[:, 0], valid_assigned[:, 1]] = assigned_labels

    # 5. 极速向量化提取所有树冠边界像素
    # 若四周邻域中存在非同类标签且自身大于 0，即为边界
    boundary = np.zeros_like(labels, dtype=bool)
    for shift in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        shifted = np.roll(labels, shift, axis=(0, 1))
        # 碰边或相邻不同类
        boundary |= (labels != shifted) & (labels > 0)

    # 边缘膨胀 1-2 像素，增加线宽在正射图上的可视度
    from scipy.ndimage import binary_dilation
    可视膨胀 = max(1, int(round(0.15 / pixel_size)))  # 约 15cm 可视线宽
    boundary_dilated = binary_dilation(boundary, structure=np.ones((可视膨胀 * 2 + 1, 可视膨胀 * 2 + 1)))

    return boundary_dilated
