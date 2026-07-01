from __future__ import annotations

import datetime
import os
import time
from pathlib import Path
from typing import Optional, Any

import numpy as np
import rasterio
import matplotlib.pyplot as plt
from loguru import logger as log

from .draw_common import (
    draw_heatmap_image,
    draw_contour_image,
    extract_and_write_shp,
    MAX_PIXELS,
)


def draw_las_main(
    las_path: str,
    image_path: str,
    dem: Optional[str] = None,
    profile_width: float = 0.5,
    threshold: float = 0.1,
    out_dir: Optional[Path] = None,
    max_valid_height: float = 8.0,
) -> int:
    """基于 LAS 点云与正射影像对齐，生成剖面图、高程热力图、等高线图与 shp 矢量图层。"""
    t_start = time.time()
    
    las_p = Path(las_path)
    img_path = Path(image_path)
    
    if not las_p.exists():
        log.error("找不到点云 LAS 文件: {}", las_path)
        return 1
    if not img_path.exists():
        log.error("找不到正射影像 DOM: {}", image_path)
        return 1

    # 1. 读入并解析 LAS 点云数据
    t0 = time.time()
    log.info("[1/7] 正在读取激光点云 LAS 文件...")
    try:
        import laspy
        las = laspy.read(las_path)
        log.info("成功载入点云，总点数: {}，耗时 {:.2f}s", len(las.points), time.time() - t0)
    except Exception as e:
        log.error("读取 LAS 点云失败: {}", e)
        return 1

    # 2. 载入 DOM 获取地理坐标边界与 RGB 信息
    t0 = time.time()
    log.info("[2/7] 正在载入正射影像 DOM 并读取地理范围与 RGB 数据...")
    try:
        with rasterio.open(image_path) as src_dom:
            dom_w = src_dom.width
            dom_h = src_dom.height
            dom_transform = src_dom.transform
            dom_crs = src_dom.crs
            dom_rgb_raw = np.transpose(src_dom.read()[:3, :, :], (1, 2, 0)).astype(np.uint8)
            
            # 计算 DOM 包围盒
            from rasterio.transform import xy
            l0, t0_coords = src_dom.xy(0, 0)
            l1, t1_coords = src_dom.xy(dom_h - 1, dom_w - 1)
            xmin_geo = min(l0, l1)
            xmax_geo = max(l0, l1)
            ymin_geo = min(t0_coords, t1_coords)
            ymax_geo = max(t0_coords, t1_coords)
            
        log.info("成功载入 DOM ({}x{})，地理边界: [{:.2f}, {:.2f}, {:.2f}, {:.2f}]，耗时 {:.2f}s",
                 dom_w, dom_h, xmin_geo, xmax_geo, ymin_geo, ymax_geo, time.time() - t0)
    except Exception as e:
        log.error("读取 DOM 失败: {}", e)
        return 1

    # 3. 按 DOM 范围空间裁剪过滤点云
    t0 = time.time()
    log.info("[3/7] 正在根据 DOM 范围对点云进行空间裁剪与坐标变换...")
    try:
        x_raw = np.array(las.x)
        y_raw = np.array(las.y)
        z_raw = np.array(las.z)
        cls_raw = np.array(las.classification) if hasattr(las, "classification") else np.zeros_like(x_raw)
        
        # 限制越界坐标
        pts_mask = (x_raw >= xmin_geo) & (x_raw <= xmax_geo) & (y_raw >= ymin_geo) & (y_raw <= ymax_geo)
        
        x_filtered = x_raw[pts_mask]
        y_filtered = y_raw[pts_mask]
        z_filtered = z_raw[pts_mask]
        cls_filtered = cls_raw[pts_mask]
        
        n_filtered = len(x_filtered)
        if n_filtered == 0:
            log.error("裁剪后无任何点云落在 DOM 包围盒内，请检查地理重合性！")
            return 1
            
        log.info("空间裁剪完成，落入 DOM 区域内的点数: {} (占 {:.2f}%)，耗时 {:.2f}s",
                 n_filtered, (n_filtered / len(las.points)) * 100, time.time() - t0)
    except Exception as e:
        log.error("空间裁剪点云失败: {}", e)
        return 1

    # 4. 估计地表基准高度 (z_base) 并计算相对高程
    t0 = time.time()
    log.info("[4/7] 正在估计每个点云的地表基准高度 (z_base)...")
    try:
        if dem and Path(dem).exists():
            log.info("使用传入的 DEM 文件作为地表高程参考: {}", dem)
            with rasterio.open(dem) as src_dem:
                from rasterio.transform import rowcol
                dem_rows, dem_cols = rowcol(src_dem.transform, x_filtered, y_filtered)
                dem_rows = np.clip(np.array(dem_rows), 0, src_dem.height - 1)
                dem_cols = np.clip(np.array(dem_cols), 0, src_dem.width - 1)
                dem_band = src_dem.read(1)
                z_base = dem_band[dem_rows, dem_cols].astype(np.float32)
                
                # 处理 DEM 的 nodata 值
                if src_dem.nodata is not None:
                    z_base = np.where(z_base == src_dem.nodata, np.nan, z_base)
                nan_mask = np.isnan(z_base)
                if np.any(nan_mask):
                    z_base[nan_mask] = np.nanmin(z_base) if not np.all(np.isnan(z_base)) else 0.0
        else:
            log.info("未提供 DEM，利用地面点云 (Class 2) 结合 KDTree 插值估计背景地表高程...")
            ground_mask = (cls_filtered == 2)
            n_ground = int(np.sum(ground_mask))
            n_total = len(z_filtered)
            
            if n_ground < n_total * 0.05 or n_ground < 100:
                coarse_sz = 5.0
                x_min, x_max = np.min(x_filtered), np.max(x_filtered)
                y_min, y_max = np.min(y_filtered), np.max(y_filtered)
                c_cols = max(1, int(np.ceil((x_max - x_min) / coarse_sz)))
                c_rows = max(1, int(np.ceil((y_max - y_min) / coarse_sz)))
                c_col_idx = np.clip(((x_filtered - x_min) / coarse_sz).astype(np.int32), 0, c_cols - 1)
                c_row_idx = np.clip(((y_max - y_filtered) / coarse_sz).astype(np.int32), 0, c_rows - 1)
                c_flat = c_row_idx * c_cols + c_col_idx
                
                min_z_grid = np.full(c_rows * c_cols, np.inf, dtype=np.float32)
                np.minimum.at(min_z_grid, c_flat, z_filtered)
                
                valid_indices = np.where(min_z_grid != np.inf)[0]
                v_rows = valid_indices // c_cols
                v_cols = valid_indices % c_cols
                v_x = x_min + (v_cols + 0.5) * coarse_sz
                v_y = y_max - (v_rows + 0.5) * coarse_sz
                v_z = min_z_grid[valid_indices]
                
                ground_coords = np.column_stack((v_x, v_y))
                ground_z = v_z
            else:
                ground_coords = np.column_stack((x_filtered[ground_mask], y_filtered[ground_mask]))
                ground_z = z_filtered[ground_mask]
                
            from scipy.spatial import cKDTree
            tree = cKDTree(ground_coords)
            dists, indices = tree.query(np.column_stack((x_filtered, y_filtered)), k=min(3, len(ground_z)))
            if dists.ndim == 1:
                z_base = ground_z[indices]
            else:
                weights = 1.0 / np.maximum(dists, 1e-6)
                w_sum = np.sum(weights, axis=1, keepdims=True)
                z_base = np.sum(ground_z[indices] * (weights / w_sum), axis=1)
                
        height_above_ground = np.maximum(0.0, z_filtered - z_base)
        # 限制有效高度上限 (避免极高电塔等杂物影响)
        height_above_ground = np.minimum(height_above_ground, max_valid_height)
        # 重构 z_filtered 以在剖面图中展现截断高度
        z_filtered = z_base + height_above_ground
        log.info("基准高度估计与高度归一化完成，耗时 {:.2f}s", time.time() - t0)
    except Exception as e:
        log.error("估计地表高度/高度归一化失败: {}", e)
        return 1

    # 5. 格网化生成 CHM 并插值填充孔洞
    t0 = time.time()
    log.info("[5/7] 正在将归一化点云高度格网化以生成 CHM 矩阵...")
    try:
        from rasterio.transform import rowcol
        rows, cols = rowcol(dom_transform, x_filtered, y_filtered)
        rows = np.clip(np.array(rows), 0, dom_h - 1)
        cols = np.clip(np.array(cols), 0, dom_w - 1)
        
        flat_idx = rows * dom_w + cols
        chm_flat = np.full(dom_h * dom_w, -1.0, dtype="float32")
        np.maximum.at(chm_flat, flat_idx, height_above_ground)
        chm = chm_flat.reshape((dom_h, dom_w))
        chm = np.where(chm == -1.0, 0.0, chm) # 填充空像素为 0
        
        # 针对点云稀疏特点，使用灰度形态学闭运算（先膨胀再腐蚀）来填充像元间的孔洞，形成连续冠幅表面。
        # 闭运算的好处是只填充内部孔洞，而不向外扩张边界，从而避免相邻树木树冠粘连。
        from scipy.ndimage import maximum_filter, minimum_filter
        pixel_size = abs(dom_transform.a)
        if pixel_size < 0.005:
            pixel_size = pixel_size * 110000.0
            
        # 动态计算 0.3 米对应的像素尺寸作为滤波核大小（30cm 是点云典型点间距）
        filter_size = int(round(0.3 / pixel_size))
        if filter_size % 2 == 0:
            filter_size += 1
        filter_size = max(3, filter_size)
        
        log.info("点云格网稀疏度填充(形态学闭运算)：GSD={:.3f}m, 滤波核大小={} 像素", pixel_size, filter_size)
        chm_dilated = maximum_filter(chm, size=filter_size)
        chm = minimum_filter(chm_dilated, size=filter_size)
        
        log.info("CHM 矩阵格网化与孔洞填充完成，耗时 {:.2f}s", time.time() - t0)
    except Exception as e:
        log.error("CHM 矩阵格网化失败: {}", e)
        return 1

    # 6. 黑边有效区域裁剪
    t0 = time.time()
    log.info("[6/7] 正在检测有效可见图像区域进行裁剪...")
    try:
        valid_mask = (dom_rgb_raw[:, :, 0] > 5) | (dom_rgb_raw[:, :, 1] > 5) | (dom_rgb_raw[:, :, 2] > 5)
        if np.any(valid_mask):
            rows_valid = np.any(valid_mask, axis=1)
            cols_valid = np.any(valid_mask, axis=0)
            ymin, ymax = np.where(rows_valid)[0][[0, -1]]
            xmin, xmax = np.where(cols_valid)[0][[0, -1]]
            
            ymin = max(0, ymin - 10)
            ymax = min(dom_h - 1, ymax + 10)
            xmin = max(0, xmin - 10)
            xmax = min(dom_w - 1, xmax + 10)
            
            dom_rgb_raw = dom_rgb_raw[ymin:ymax+1, xmin:xmax+1]
            chm = chm[ymin:ymax+1, xmin:xmax+1]
            
            from rasterio.transform import Affine
            dom_transform = dom_transform * Affine.translation(xmin, ymin)
            dom_w = xmax - xmin + 1
            dom_h = ymax - ymin + 1
            log.info("有效图像裁剪完成，新尺寸: ({}x{})，耗时 {:.2f}s", dom_w, dom_h, time.time() - t0)
        else:
            log.warning("未检测到有效可见区域，跳过裁剪。")
    except Exception as e:
        log.error("执行黑边裁剪失败: {}", e)
        return 1

    # 7. 安全控制降采样 (防 Matplotlib 卡死/OOM)
    t0 = time.time()
    total_pixels = dom_w * dom_h
    if total_pixels > MAX_PIXELS:
        from PIL import Image
        from rasterio.transform import Affine
        scale = np.sqrt(MAX_PIXELS / total_pixels)
        new_w = int(round(dom_w * scale))
        new_h = int(round(dom_h * scale))
        log.info("图像像素 {} 超过限额 {}，自适应下采样至 {}x{} 以避免 Matplotlib 卡顿...",
                 total_pixels, MAX_PIXELS, new_w, new_h)
                 
        img_pil = Image.fromarray(dom_rgb_raw)
        dom_rgb_raw_draw = np.array(img_pil.resize((new_w, new_h), resample=Image.BILINEAR))
        
        chm_pil = Image.fromarray(chm)
        chm_draw = np.array(chm_pil.resize((new_w, new_h), resample=Image.BILINEAR))
        
        dom_transform_draw = dom_transform * Affine.scale(1.0 / scale, 1.0 / scale)
        log.info("降采样完成，耗时 {:.2f}s", time.time() - t0)
    else:
        dom_rgb_raw_draw = dom_rgb_raw
        chm_draw = chm
        dom_transform_draw = dom_transform
        log.info("图像未超出尺寸限制，直接以原始分辨率进行制图。")

    # 创建输出目录
    if out_dir is not None:
        out_dir = Path(out_dir)
    else:
        from .. import paths
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        out_dir = paths.subdir("tmp") / "draw_las" / f"{timestamp}_{las_p.stem}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 8. 绘制输出
    t0 = time.time()
    log.info("[7/7] 正在生成垂直剖面图、高程热力图、等高线图与矢量 Shapefile...")
    try:
        # a. 垂直条带剖面图
        _draw_vertical_profile(
            x_filtered, y_filtered, z_filtered, cls_filtered,
            profile_width, dem, dom_transform, dom_crs, out_dir / "point_cloud_profile.jpg",
            z_base=z_base
        )
        print(f"Success Profile Image: {out_dir / 'point_cloud_profile.jpg'}")
        
        # b. 热力图
        draw_heatmap_image(dom_rgb_raw_draw, chm_draw, threshold, dom_transform_draw, out_dir / "heatmap.jpg")
        print(f"Success Heatmap: {out_dir / 'heatmap.jpg'}")
        
        # c. 导出 shp 矢量多边形文件
        mask_shp = chm >= threshold
        extract_and_write_shp(mask_shp, dom_transform, dom_crs, out_dir / "contours.shp")
        print(f"Success Vector: {out_dir / 'contours.shp'}")
        
        # d. 轮廓图
        mask_draw = chm_draw >= threshold
        draw_contour_image(dom_rgb_raw_draw, mask_draw, dom_transform_draw, out_dir / "contour.jpg")
        print(f"Success Contour: {out_dir / 'contour.jpg'}")
        
        log.info("全部制图渲染成功，耗时 {:.2f}s", time.time() - t0)
    except Exception as e:
        log.error("绘制图层失败: {}", e)
        return 1

    log.info("激光点云可视化任务全部执行完成，端到端总耗时: {:.2f}s", time.time() - t_start)
    return 0


def _draw_vertical_profile(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    cls: np.ndarray,
    profile_width: float,
    dem_path: Optional[str],
    dom_transform: Any,
    dom_crs: Any,
    out_path: Path,
    z_base: Optional[np.ndarray] = None,
) -> None:
    """横切生成高密度剖面散点图，若提供 DEM，则在其上绘制连续红色地形线。"""
    # 1. 沿南北方向 (Y轴) 划定中心横剖线，提取落在剖面宽度范围内的点
    y_min, y_max = np.min(y), np.max(y)
    y_mid = (y_min + y_max) / 2.0
    
    # 获取切面缓冲区掩膜 (y_mid ± width/2)
    half_w = profile_width / 2.0
    mask_prof = (y >= (y_mid - half_w)) & (y <= (y_mid + half_w))
    
    x_prof = x[mask_prof]
    y_prof = y[mask_prof]
    z_prof = z[mask_prof]
    cls_prof = cls[mask_prof]
    z_base_prof = z_base[mask_prof] if z_base is not None else None
    
    if len(x_prof) == 0:
        raise ValueError(f"拉切带内无点云。请扩大 profile_width (当前: {profile_width}m)")
        
    # 东西向跨度超过 50 米，则只截取切片的中间 50 米
    x_min_prof, x_max_prof = np.min(x_prof), np.max(x_prof)
    slice_length = x_max_prof - x_min_prof
    if slice_length > 50.0:
        x_mid = (x_min_prof + x_max_prof) / 2.0
        mask_len = (x_prof >= x_mid - 25.0) & (x_prof <= x_mid + 25.0)
        x_prof = x_prof[mask_len]
        y_prof = y_prof[mask_len]
        z_prof = z_prof[mask_len]
        cls_prof = cls_prof[mask_len]
        if z_base_prof is not None:
            z_base_prof = z_base_prof[mask_len]
            
    # 2. 绘图：不抽稀，高密度展现
    fig, ax = plt.subplots(figsize=(16, 6), dpi=300)
    
    is_ground = (cls_prof == 2)
    
    # 植被点用 viridis 彩虹色，展现高度阶梯
    if np.any(~is_ground):
        sc_veg = ax.scatter(
            x_prof[~is_ground], z_prof[~is_ground],
            c=z_prof[~is_ground], cmap="viridis",
            s=1.2, alpha=0.9, label="Vegetation Points",
            rasterized=True
        )
        cbar = fig.colorbar(sc_veg, ax=ax, shrink=0.7, pad=0.02)
        cbar.set_label("Elevation (m)", fontsize=11, fontweight='bold')
        
    # 地面点用柔和的深灰色画在最底下
    if np.any(is_ground):
        ax.scatter(
            x_prof[is_ground], z_prof[is_ground],
            color="#555555", s=0.8, alpha=0.5,
            label="Ground Points", rasterized=True
        )

    # 3. 绘制地表 DEM 影像/高程线
    has_dem_drawn = False
    if dem_path and Path(dem_path).exists():
        try:
            with rasterio.open(dem_path) as src_dem:
                x_min_prof, x_max_prof = np.min(x_prof), np.max(x_prof)
                sample_xs = np.linspace(x_min_prof, x_max_prof, 300)
                sample_ys = np.full_like(sample_xs, y_mid)
                
                from rasterio.transform import rowcol
                dem_rows, dem_cols = rowcol(src_dem.transform, sample_xs, sample_ys)
                dem_rows = np.clip(np.array(dem_rows), 0, src_dem.height - 1)
                dem_cols = np.clip(np.array(dem_cols), 0, src_dem.width - 1)
                
                dem_band = src_dem.read(1)
                dem_zs = dem_band[dem_rows, dem_cols]
                
                ax.plot(
                    sample_xs, dem_zs, color="#ff4a4a", linewidth=2.0,
                    linestyle="-", label="DEM Ground Surface", zorder=10
                )
                has_dem_drawn = True
        except Exception as e:
            log.warning("在剖面图上绘制 DEM 地形线失败: {}", e)
            
    if not has_dem_drawn and z_base_prof is not None and len(x_prof) > 0:
        try:
            # 根据 x 进行排序以绘制平滑的地表红线
            sort_idx = np.argsort(x_prof)
            ax.plot(
                x_prof[sort_idx], z_base_prof[sort_idx], color="#ff4a4a", linewidth=2.0,
                linestyle="-", label="Estimated DEM Ground Surface", zorder=10
            )
        except Exception as e:
            log.warning("绘制估计的 DEM 剖面地形线失败: {}", e)

    # 4. 图纸美化与整饰
    ax.set_xlabel("Longitude (E)", fontsize=11)
    ax.set_ylabel("Elevation / Height (m)", fontsize=11)
    ax.set_title(
        f"Forest Canopy Vertical Profile Section (Width: {profile_width}m, Slice Y: {y_mid:.4f})",
        fontsize=14, fontweight='bold', pad=15
    )
    
    ax.legend(loc="upper right", framealpha=0.9, facecolor="white")
    ax.grid(True, linestyle="--", alpha=0.4)
    
    plt.tight_layout()
    plt.savefig(out_path, bbox_inches="tight", dpi=300)
    plt.close()
