from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patheffects as path_effects
from loguru import logger as log
from scipy.ndimage import binary_opening

# 背景彩色弱化调节参数
BG_DESATURATE = 0.5  
BG_ALPHA = 0.85      
MAX_PIXELS = 25000000


def decorate_axes(ax: plt.Axes, H: int, W: int, dom_transform: Any) -> None:
    """在坐标轴上渲染指北针、物理比例尺与经纬度地理刻度。"""
    tick_indices = np.linspace(0, W - 1, 5)
    xtick_labels = []
    ytick_labels = []
    for tick in tick_indices:
        lon, _ = dom_transform * (tick, 0)
        _, lat = dom_transform * (0, tick)
        xtick_labels.append(f"{lon:.4f}°E")
        ytick_labels.append(f"{lat:.4f}°N")
        
    ax.set_xticks(tick_indices)
    ax.set_xticklabels(xtick_labels, fontsize=9)
    ax.set_yticks(tick_indices)
    ax.set_yticklabels(ytick_labels, fontsize=9)

    north_x = int(W * 0.92)
    north_y_arrow = int(H * 0.06)
    north_y_text = int(H * 0.11)
    ax.annotate('N', xy=(north_x, north_y_arrow), xytext=(north_x, north_y_text),
                arrowprops=dict(facecolor='white', edgecolor='black', width=4, headwidth=14, shrink=0.05),
                ha='center', va='center', fontsize=22, fontweight='bold', color='white',
                path_effects=[path_effects.withStroke(linewidth=3, foreground='black')])

    lat_val = 20.5849
    m_per_deg_lon = 111320.0 * np.cos(np.radians(lat_val))
    lon0, _ = dom_transform * (0, 0)
    lon100, _ = dom_transform * (100, 0)
    gsd_m = (abs(lon100 - lon0) / 100.0) * m_per_deg_lon

    ground_width_m = W * gsd_m
    if ground_width_m > 30.0:
        scale_val_m = 10.0
    else:
        scale_val_m = 2.0

    scale_bar_len_px = scale_val_m / gsd_m
    scale_y = int(H * 0.93)
    scale_x_start = int(W * 0.08)
    scale_x_end = scale_x_start + scale_bar_len_px

    ax.plot([scale_x_start, scale_x_end], [scale_y, scale_y], color='white', linewidth=8, solid_capstyle='butt')
    ax.plot([scale_x_start, scale_x_end], [scale_y, scale_y], color='black', linewidth=3, solid_capstyle='butt')
    ax.text((scale_x_start + scale_x_end) / 2.0, scale_y - int(H * 0.015), f"{int(scale_val_m)} m", 
            color='white', fontsize=14, fontweight='bold', ha='center', va='bottom',
            path_effects=[path_effects.withStroke(linewidth=3, foreground='black')])


def draw_heatmap_image(
    dom_rgb_raw: np.ndarray,
    chm: np.ndarray,
    threshold: float,
    dom_transform: Any,
    out_path: Path,
) -> bool:
    """绘制论文级 CHM 高程热力图。"""
    try:
        gray = (0.299 * dom_rgb_raw[:, :, 0] + 0.587 * dom_rgb_raw[:, :, 1] + 0.114 * dom_rgb_raw[:, :, 2]).astype(np.float32)
        gray_rgb = np.stack([gray, gray, gray], axis=-1)
        dom_rgb = (dom_rgb_raw.astype(np.float32) * (1.0 - BG_DESATURATE) + gray_rgb * BG_DESATURATE).astype(np.uint8)

        H, W = dom_rgb.shape[:2]
        fig, ax = plt.subplots(figsize=(12, 10), dpi=300)
        
        ax.imshow(dom_rgb, alpha=BG_ALPHA)
        
        chm_masked = np.where(chm >= threshold, chm, np.nan)
        im = ax.imshow(chm_masked, cmap="viridis", vmin=threshold, alpha=0.65)
        
        decorate_axes(ax, H, W, dom_transform)
        
        cbar = fig.colorbar(im, ax=ax, shrink=0.8)
        cbar.set_label("Relative Canopy Height (meters)", fontsize=12, fontweight='bold')
        
        ax.set_title(f"CHM Elevation Heatmap Overlay (Threshold: {threshold:.2f}m)", fontsize=14, fontweight='bold', pad=18)
        ax.set_xlabel("Longitude", fontsize=11)
        ax.set_ylabel("Latitude", fontsize=11)
        
        plt.tight_layout()
        plt.savefig(out_path, bbox_inches="tight", dpi=300)
        plt.close()
        return True
    except Exception as e:
        log.error("绘制热力图失败: {}", e)
        return False


def draw_contour_image(
    dom_rgb_raw: np.ndarray,
    mask: np.ndarray,
    dom_transform: Any,
    out_path: Path,
) -> bool:
    """绘制带树冠二值轮廓线的叠加影像。"""
    try:
        gray = (0.299 * dom_rgb_raw[:, :, 0] + 0.587 * dom_rgb_raw[:, :, 1] + 0.114 * dom_rgb_raw[:, :, 2]).astype(np.float32)
        gray_rgb = np.stack([gray, gray, gray], axis=-1)
        dom_rgb = (dom_rgb_raw.astype(np.float32) * (1.0 - BG_DESATURATE) + gray_rgb * BG_DESATURATE).astype(np.uint8)

        H, W = dom_rgb.shape[:2]
        fig, ax = plt.subplots(figsize=(12, 10), dpi=300)
        
        ax.imshow(dom_rgb, alpha=BG_ALPHA)
        
        # 过滤孤立微小像素（降噪且防止 matplotlib 绘制过多等高线导致卡死）
        mask_clean = binary_opening(mask, structure=np.ones((3, 3)))
        if np.any(mask_clean):
            x = np.arange(W)
            y = np.arange(H)
            ax.contour(x, y, mask_clean, levels=[0.5], colors=['#00f0ff'], linewidths=1.2)
        
        decorate_axes(ax, H, W, dom_transform)
        
        ax.set_title("Canopy Contour Overlay", fontsize=14, fontweight='bold', pad=18)
        ax.set_xlabel("Longitude", fontsize=11)
        ax.set_ylabel("Latitude", fontsize=11)
        
        plt.tight_layout()
        plt.savefig(out_path, bbox_inches="tight", dpi=300)
        plt.close()
        return True
    except Exception as e:
        log.error("绘制轮廓图失败: {}", e)
        return False


def extract_and_write_shp(mask: np.ndarray, transform: Any, crs: Any, shp_path: Path) -> None:
    """提取二值掩膜为多边形并写入 Shapefile。"""
    try:
        import geopandas as gpd
        from shapely.geometry import shape
        from rasterio.features import shapes
    except ImportError as e:
        log.error("缺少 geopandas/shapely/rasterio 依赖: {}", e)
        return

    # 过滤噪点，避免微小多边形（如单像素）导致 shapely/GEOS 崩溃或生成超大 Shapefile
    mask_clean = binary_opening(mask, structure=np.ones((3, 3)))
    mask_int = mask_clean.astype(np.uint8)
    shape_gen = shapes(mask_int, mask=(mask_int == 1), transform=transform)
    records = []
    for geom, val in shape_gen:
        poly = shape(geom)
        records.append({"geometry": poly, "val": float(val), "is_crown": 1})

    if records:
        gdf = gpd.GeoDataFrame(records, crs=crs)
        gdf.to_file(shp_path)
        log.info("成功导出矢量轮廓: {}", shp_path)
    else:
        gdf = gpd.GeoDataFrame(columns=["geometry", "val", "is_crown"], crs=crs)
        gdf.to_file(shp_path)
        log.warning("CHM 区域二值化无有效像素，导出了空 Shapefile")
