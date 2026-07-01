from __future__ import annotations

import datetime
import os
import time
from pathlib import Path
from typing import Optional, Any

import numpy as np
import rasterio
from loguru import logger as log
from scipy.ndimage import gaussian_filter, minimum_filter

from .draw_common import (
    draw_heatmap_image,
    draw_contour_image,
    extract_and_write_shp,
    MAX_PIXELS,
)


def draw_dsm_main(
    image_path: str,
    dsm_path: str,
    dem: Optional[str] = None,
    mode: str = "both",
    threshold: float = 0.1,
    out_dir: Optional[Path] = None,
    max_valid_height: float = 8.0,
) -> int:
    """基于 DSM/DEM 差分在影像上绘制并生成高程热力图或矢量轮廓文件。"""
    t_start = time.time()
    
    from .. import paths
    from ..fusion.crown import verify_overlap
    from rasterio.warp import reproject, Resampling
    from PIL import Image
    
    img_path = Path(image_path)
    dsm_p = Path(dsm_path)
    
    if not img_path.exists():
        log.error("找不到正射影像 DOM: {}", image_path)
        return 1
    if not dsm_p.exists():
        log.error("找不到高程影像 DSM: {}", dsm_path)
        return 1

    # 1. 验证包含性地理重合
    t0 = time.time()
    try:
        verify_overlap(image_path, dsm_path)
        log.info("[步骤 1/7] 地理重合关系校验通过，耗时 {:.2f}s", time.time() - t0)
    except ValueError as e:
        log.error("地理包含性检查失败: {}", e)
        return 1

    # 2. 载入原始 DOM 的地理坐标系参数与 RGB 彩色矩阵
    t0 = time.time()
    log.info("[步骤 2/7] 正在载入正射影像 DOM 并读取地理参数...")
    try:
        with rasterio.open(image_path) as src_dom:
            dom_width = src_dom.width
            dom_height = src_dom.height
            dom_transform = src_dom.transform
            dom_crs = src_dom.crs
            dom_rgb_raw = np.transpose(src_dom.read()[:3, :, :], (1, 2, 0)).astype(np.uint8)
        log.info("成功载入 DOM ({}x{})，耗时 {:.2f}s", dom_width, dom_height, time.time() - t0)
    except Exception as e:
        log.error("读取 DOM 失败: {}", e)
        return 1

    total_pixels = dom_width * dom_height

    # 🔴 关键安全控制：若原始图像像素超出 2500 万限制，立刻在重投影前进行自适应下采样！
    # 彻底杜绝 7 亿像素下 reproject 分配 3GB 内存造成的 Segfault 崩溃
    if total_pixels > MAX_PIXELS:
        t0 = time.time()
        scale = np.sqrt(MAX_PIXELS / total_pixels)
        new_w = int(round(dom_width * scale))
        new_h = int(round(dom_height * scale))
        log.info("图像像素 {} 超过限额 {}，执行重投影前置下采样至 {}x{} 以防内存溢出(Segfault/OOM)...",
                 total_pixels, MAX_PIXELS, new_w, new_h)
                 
        img_pil = Image.fromarray(dom_rgb_raw)
        dom_rgb_raw = np.array(img_pil.resize((new_w, new_h), resample=Image.BILINEAR))
        
        from rasterio.transform import Affine
        dom_transform = dom_transform * Affine.scale(1.0 / scale, 1.0 / scale)
        
        dom_width = new_w
        dom_height = new_h
        total_pixels = dom_width * dom_height
        log.info("前置自适应下采样与地理变换矩阵调整完成，耗时 {:.2f}s", time.time() - t0)

    # 3. 空间重投影对齐 DSM (内存安全级)
    t0 = time.time()
    log.info("[步骤 3/7] 正在执行 DOM 与 DSM 空间对齐重投影...")
    try:
        dsm_aligned = np.full((dom_height, dom_width), np.nan, dtype="float32")
        with rasterio.open(dsm_path) as src_dsm:
            reproject(
                source=rasterio.band(src_dsm, 1),
                destination=dsm_aligned,
                src_transform=src_dsm.transform,
                src_crs=src_dsm.crs,
                dst_transform=dom_transform,
                dst_crs=dom_crs,
                resampling=Resampling.bilinear,
                src_nodata=src_dsm.nodata,
                dst_nodata=np.nan,
            )
        log.info("DSM 重投影对齐完成，耗时 {:.2f}s", time.time() - t0)
    except Exception as e:
        log.error("对齐 DSM 失败: {}", e)
        return 1

    # 4. 获取 DEM 影像并进行空间对齐
    t0 = time.time()
    dem_aligned = None
    if dem:
        dem_p_arg = Path(dem)
        if dem_p_arg.exists():
            log.info("[步骤 4/7] 正在执行 DOM 与输入 DEM ({}) 的空间重投影对齐...", dem)
            try:
                dem_aligned = np.full((dom_height, dom_width), np.nan, dtype="float32")
                with rasterio.open(dem) as src_dem:
                    reproject(
                        source=rasterio.band(src_dem, 1),
                        destination=dem_aligned,
                        src_transform=src_dem.transform,
                        src_crs=src_dem.crs,
                        dst_transform=dom_transform,
                        dst_crs=dom_crs,
                        resampling=Resampling.bilinear,
                        src_nodata=src_dem.nodata,
                        dst_nodata=np.nan,
                    )
                log.info("DEM 重投影对齐完成，耗时 {:.2f}s", time.time() - t0)
            except Exception as e:
                log.warning("对齐输入 DEM 失败，将降级为无 DEM 高程背景估计: {}", e)
                dem_aligned = None
        else:
            log.warning("未找到指定的 DEM 路径: {}, 将降级为无 DEM 估计模式", dem)
    else:
        log.info("[步骤 4/7] 未指定 DEM，跳过 DEM 重投影对齐。")
    
    # 5. 计算 CHM (DSM - DEM)
    t0 = time.time()
    if dem_aligned is not None:
        log.info("[步骤 5/7] 使用 DSM - DEM 直接像素差分计算相对高程 CHM (无平滑)...")
        dsm_filled = dsm_aligned.copy()
        dsm_filled[np.isnan(dsm_filled)] = 0.0
        dem_filled = dem_aligned.copy()
        dem_filled[np.isnan(dem_filled)] = 0.0
        chm = np.maximum(0.0, dsm_filled - dem_filled)
    else:
        log.info("[步骤 5/7] 采用形态学最小滤波器估计背景 DEM 并差分计算 CHM...")
        pixel_size = abs(dom_transform.a)
        if pixel_size < 0.005:
            pixel_size = pixel_size * 110000.0
            
        bg_win = int(round(20.0 / pixel_size))
        if bg_win % 2 == 0:
            bg_win += 1
        bg_win = max(5, bg_win)
        
        dsm_filled = dsm_aligned.copy()
        dsm_filled[np.isnan(dsm_filled)] = np.nanmean(dsm_filled) if not np.all(np.isnan(dsm_filled)) else 0.0
        
        smoothed = gaussian_filter(dsm_filled, sigma=max(1.0, 0.5 / pixel_size))
        dem_est = minimum_filter(smoothed, size=bg_win)
        chm = np.maximum(0.0, dsm_filled - dem_est)

    chm[np.isnan(chm)] = 0.0
    # 限制最大有效高度 (避免极高电塔等杂物影响)
    chm = np.minimum(chm, max_valid_height)
    log.info("CHM 计算完成，限制最大有效高度 {}m，耗时 {:.2f}s", max_valid_height, time.time() - t0)

    # 6. 自动寻找肉眼可见的有效图像区域进行边界裁剪
    t0 = time.time()
    valid_mask = (dom_rgb_raw[:, :, 0] > 5) | (dom_rgb_raw[:, :, 1] > 5) | (dom_rgb_raw[:, :, 2] > 5)
    if np.any(valid_mask):
        rows = np.any(valid_mask, axis=1)
        cols = np.any(valid_mask, axis=0)
        ymin, ymax = np.where(rows)[0][[0, -1]]
        xmin, xmax = np.where(cols)[0][[0, -1]]
        
        # 给有效边界向外扩充 10 个像素的 buffer（但不能超出原始边界）
        ymin = max(0, ymin - 10)
        ymax = min(dom_height - 1, ymax + 10)
        xmin = max(0, xmin - 10)
        xmax = min(dom_width - 1, xmax + 10)
        
        cropped_w = xmax - xmin + 1
        cropped_h = ymax - ymin + 1
        
        log.info("[步骤 6/7] 检测到有效图像区域边界 (xmin={}, ymin={}, xmax={}, ymax={})，执行黑边裁剪...",
                 xmin, ymin, xmax, ymax)
        
        # 对 DOM, CHM 执行切片裁剪
        dom_rgb_raw = dom_rgb_raw[ymin:ymax+1, xmin:xmax+1]
        chm = chm[ymin:ymax+1, xmin:xmax+1]
        
        # 调整仿射变换，平移至裁剪后的左上角地理原点
        from rasterio.transform import Affine
        dom_transform = dom_transform * Affine.translation(xmin, ymin)
        
        # 更新宽、高和总像素值
        dom_width = cropped_w
        dom_height = cropped_h
        total_pixels = dom_width * dom_height
        log.info("黑边裁剪完成，裁剪后尺寸为 ({}x{})，耗时 {:.2f}s", dom_width, dom_height, time.time() - t0)
    else:
        log.warning("[步骤 6/7] 未检测到任何有效可见像素，跳过裁剪。")

    # 7. 计算制图自适应下采样，为防 Matplotlib 卡死/OOM
    t0 = time.time()
    if total_pixels > MAX_PIXELS:
        from PIL import Image
        from rasterio.transform import Affine
        
        scale = np.sqrt(MAX_PIXELS / total_pixels)
        new_w = int(round(dom_width * scale))
        new_h = int(round(dom_height * scale))
        log.info("[步骤 7/7] 图像像素 {} 超过限额 {}，自适应下采样至 {}x{} 以避免 Matplotlib 卡顿...",
                 total_pixels, MAX_PIXELS, new_w, new_h)
                 
        img_pil = Image.fromarray(dom_rgb_raw)
        dom_rgb_raw_draw = np.array(img_pil.resize((new_w, new_h), resample=Image.BILINEAR))
        
        chm_pil = Image.fromarray(chm)
        chm_draw = np.array(chm_pil.resize((new_w, new_h), resample=Image.BILINEAR))
        
        dom_transform_draw = dom_transform * Affine.scale(1.0 / scale, 1.0 / scale)
        log.info("图像降采样与地理空间缩放完成，耗时 {:.2f}s", time.time() - t0)
    else:
        dom_rgb_raw_draw = dom_rgb_raw
        chm_draw = chm
        dom_transform_draw = dom_transform
        log.info("[步骤 7/7] 图像未超出尺寸限制，直接以原始分辨率进行制图。")

    # 创建输出目录
    if out_dir is not None:
        out_dir = Path(out_dir)
    else:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        out_dir = paths.subdir("tmp") / "draw_dsm" / f"{timestamp}_{img_path.stem}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 8. 执行模式分支与渲染
    if mode == "heatmap":
        t0 = time.time()
        log.info("热力图模式：开始绘制论文级高程热力图...")
        success = draw_heatmap_image(
            dom_rgb_raw_draw, chm_draw, threshold, dom_transform_draw, out_dir / "heatmap.jpg"
        )
        if success:
            log.info("热力图渲染成功，耗时 {:.2f}s，输出: {}", time.time() - t0, out_dir / 'heatmap.jpg')
            print(f"Success: {out_dir / 'heatmap.jpg'}")
            log.info("任务全部执行完成，端到端总耗时: {:.2f}s", time.time() - t_start)
            return 0
        return 1

    elif mode == "contour":
        # a. 导出 shp 矢量多边形文件（始终基于原始最高分辨率）
        t0 = time.time()
        log.info("轮廓线模式：开始提取二值掩膜 (chm >= {:.2f}m) 并输出矢量 Shapefile...", threshold)
        mask = chm >= threshold
        extract_and_write_shp(mask, dom_transform, dom_crs, out_dir / "contours.shp")
        log.info("Shapefile 矢量提取成功，耗时 {:.2f}s", time.time() - t0)
        
        # b. 渲染轮廓线叠加 JPG 图像（基于下采样后的分辨率防卡死）
        t0 = time.time()
        log.info("开始渲染轮廓线叠加图...")
        mask_draw = chm_draw >= threshold
        draw_contour_image(dom_rgb_raw_draw, mask_draw, dom_transform_draw, out_dir / "contour.jpg")
        log.info("轮廓图渲染成功，耗时 {:.2f}s", time.time() - t0)
        
        print(f"Success: {out_dir / 'contour.jpg'}")
        print(f"Success Vector: {out_dir / 'contours.shp'}")
        log.info("任务全部执行完成，端到端总耗时: {:.2f}s", time.time() - t_start)
        return 0

    else:
        # both 模式 (默认)
        log.info("Both模式：开始同时渲染热力图与提取矢量轮廓...")
        
        # a. 渲染热力图
        t0 = time.time()
        draw_heatmap_image(dom_rgb_raw_draw, chm_draw, threshold, dom_transform_draw, out_dir / "heatmap.jpg")
        log.info("[Both] 热力图渲染成功，耗时 {:.2f}s", time.time() - t0)
        
        # b. 导出 shp 矢量多边形文件（始终基于原始最高分辨率）
        t0 = time.time()
        mask = chm >= threshold
        extract_and_write_shp(mask, dom_transform, dom_crs, out_dir / "contours.shp")
        log.info("[Both] Shapefile 矢量提取成功，耗时 {:.2f}s", time.time() - t0)
        
        # c. 渲染轮廓线叠加图
        t0 = time.time()
        mask_draw = chm_draw >= threshold
        draw_contour_image(dom_rgb_raw_draw, mask_draw, dom_transform_draw, out_dir / "contour.jpg")
        log.info("[Both] 轮廓图渲染成功，耗时 {:.2f}s", time.time() - t0)
        
        print(f"Success Heatmap: {out_dir / 'heatmap.jpg'}")
        print(f"Success Contour: {out_dir / 'contour.jpg'}")
        print(f"Success Vector: {out_dir / 'contours.shp'}")
        log.info("任务全部执行完成，端到端总耗时: {:.2f}s", time.time() - t_start)
        return 0



