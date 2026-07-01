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
    from .chm import load_single_band
    try:
        # 使用 rasterio 或 geo 提取
        # 为了不完全读入大图，可以使用较轻量级的 geo 获取
        dom_geo = resolve_geo(dom_path)
        dsm_geo = resolve_geo(dsm_path)
    except Exception as e:
        log.warning("读取地理空间信息失败，跳过重合性检查: {}", e)
        return

    if not dom_geo.transform or not dsm_geo.transform:
        log.warning("影像缺少仿射变换信息，跳过重合性检查。")
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
        log.error("{}", err_msg)
        raise ValueError(err_msg)

    log.info("DOM/DSM 地理包含关系验证通过。")


def align_dsm_to_dom(dsm_path: str, dom_path: str) -> Tuple[np.ndarray, np.ndarray, Optional[Affine]]:
    """将 DSM 栅格重投影并对齐到 DOM 相同的空间格网中。
    
    返回:
        dsm_aligned: 对齐后的 DSM 阵列
        dom_arr: DOM 本身对应的单通道/灰度化数据（用来确定形状）
        dom_transform: DOM 的地理仿射矩阵
    """
    from .chm import load_single_band
    dom_arr, dom_geo = load_single_band(dom_path)
    dsm_arr, dsm_geo = load_single_band(dsm_path)

    if dom_arr.shape == dsm_arr.shape:
        log.info("DOM 与 DSM 分辨率和尺寸一致，跳过重投影。")
        return dsm_arr, dom_arr, (dom_geo.transform if dom_geo else None)

    log.info(
        "DOM 尺寸={} 与 DSM 尺寸={} 不一致，执行空间重投影对齐...",
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
        log.info("DSM 重投影对齐完成。")
        return dsm_aligned, dom_arr, Affine.from_rasterio(src_dom.transform)
    except Exception as e:
        log.warning("自动重投影失败，降级为直接截取/缩放对齐: {}", e)
        # 降级：通过插值将 dsm 缩放到与 dom 相同大小
        from PIL import Image
        dsm_im = Image.fromarray(dsm_arr)
        dsm_resized = dsm_im.resize((dom_arr.shape[1], dom_arr.shape[0]), resample=Image.BILINEAR)
        return np.array(dsm_resized, dtype="float32"), dom_arr, (dom_geo.transform if dom_geo else None)


def estimate_canopy_contours(
    dsm_arr: np.ndarray,
    transform: Optional[Affine] = None,
    chm_threshold: float = 0.1,
    max_crown_radius: float = 3.0,
    dem_arr: Optional[np.ndarray] = None,
) -> np.ndarray:
    """基于 DSM 数字表面模型，通过简单的相对高度二值化提取高程地物外轮廓 (无需复杂 Voronoi/种子点分割)"""
    try:
        from scipy.ndimage import gaussian_filter, minimum_filter, binary_dilation
    except ImportError as e:
        log.error("缺少 scipy: {}", e)
        raise e

    # 1. 确定空间分辨率
    if transform:
        if hasattr(transform, "pixel_size_x"):
            pixel_size = abs(transform.pixel_size_x())
        elif hasattr(transform, "a"):
            pixel_size = abs(transform.a)
        else:
            pixel_size = 0.1
    else:
        pixel_size = 0.1
    if pixel_size < 0.005:
        pixel_size = pixel_size * 110000.0

    # 2. 对 DSM 填充 NaN 以防干扰
    dsm_filled = dsm_arr.copy()
    dsm_filled[np.isnan(dsm_filled)] = np.nanmean(dsm_filled) if not np.all(np.isnan(dsm_filled)) else 0.0

    # 3. 计算相对高度 CHM
    if dem_arr is not None and dem_arr.size > 0:
        dem_filled = dem_arr.copy()
        dem_filled[np.isnan(dem_filled)] = np.nanmean(dem_filled) if not np.all(np.isnan(dem_filled)) else 0.0
        # 考虑到高程本身的微小起伏，我们可以先高斯平滑
        smoothed_dsm = gaussian_filter(dsm_filled, sigma=max(1.0, 0.5 / pixel_size))
        smoothed_dem = gaussian_filter(dem_filled, sigma=max(1.0, 0.5 / pixel_size))
        chm = np.maximum(0.0, smoothed_dsm - smoothed_dem)
    else:
        bg_win = int(round(20.0 / pixel_size))
        if bg_win % 2 == 0:
            bg_win += 1
        bg_win = max(5, bg_win)
        smoothed = gaussian_filter(dsm_filled, sigma=max(1.0, 0.5 / pixel_size))
        dem_est = minimum_filter(smoothed, size=bg_win)
        chm = np.maximum(0.0, smoothed - dem_est)

    # 4. 极速简单高度二值化 mask (截断阈值，使用配置的 chm_threshold)
    mask = chm >= chm_threshold
    
    # 5. 提取二值掩膜的交界轮廓像素 (用向四周 roll 后比对)
    boundary = np.zeros_like(mask, dtype=bool)
    for shift in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        shifted = np.roll(mask, shift, axis=(0, 1))
        boundary |= (mask != shifted) & mask

    # 膨胀 1-2 像素，使其在叠加图上有较好可视厚度
    dilate_win = max(1, int(round(0.15 / pixel_size)))
    boundary_dilated = binary_dilation(boundary, structure=np.ones((dilate_win * 2 + 1, dilate_win * 2 + 1)))

    return boundary_dilated

