"""TIFF 影像裁剪工具。

职责：
  - 仅支持 TIFF 格式影像。
  - 支持中心裁剪（num_crops=0）或随机无重叠且控制 nodata 占比的物理裁剪（num_crops > 0）。
"""
from __future__ import annotations

import os
import random
from pathlib import Path
import numpy as np
import rasterio
from PIL import Image
from rasterio.windows import Window, transform as w_transform
from loguru import logger


def check_overlap(win1: Window, win2: Window) -> bool:
    """检查两个 rasterio.windows.Window 是否重叠"""
    x1, y1, w1, h1 = win1.col_off, win1.row_off, win1.width, win1.height
    x2, y2, w2, h2 = win2.col_off, win2.row_off, win2.width, win2.height
    return not (x1 + w1 <= x2 or x2 + w2 <= x1 or y1 + h1 <= y2 or y2 + h2 <= y1)


def get_nodata_ratio(src: rasterio.DatasetReader, window: Window, nodata_val: float | None) -> float:
    """计算窗口内 nodata 数据的占比"""
    # 读取第一波段加速计算
    data = src.read(1, window=window)
    
    if nodata_val is not None:
        if np.isnan(nodata_val):
            return float(np.mean(np.isnan(data)))
        else:
            return float(np.mean(data == nodata_val))
    else:
        # 未定义 nodata 时，默认将 0 视为 nodata
        return float(np.mean(data == 0))


def numpy_to_rgb_image(data: np.ndarray) -> Image.Image:
    """将多通道或单通道的 numpy array 转换为 uint8 的 PIL RGB Image，保留原始色彩与数值。"""
    # 期望输入为 (channels, height, width)
    if data.ndim == 3:
        if data.shape[0] >= 3:
            # 取前三个通道，假设为 RGB
            rgb = data[:3, :, :]
        else:
            # 复制单通道
            rgb = np.repeat(data[0:1, :, :], 3, axis=0)
    elif data.ndim == 2:
        rgb = np.repeat(data[np.newaxis, :, :], 3, axis=0)
    else:
        raise ValueError(f"不支持的数据维度: {data.ndim}")
        
    # 转为 (height, width, channels)
    rgb = np.transpose(rgb, (1, 2, 0))
    
    # 仅填充 NaN 值，直接转换为 uint8
    rgb = np.nan_to_num(rgb, nan=0.0)
    rgb_uint8 = rgb.astype(np.uint8)
    return Image.fromarray(rgb_uint8)


def crop_tiff_main(
    input_path: str | Path,
    output_dir: str | Path | None = None,
    num_crops: int = 3,
    size: int = 5000,
    nodata_tolerance: float = 0.05,
    vector_path: str | Path | None = None,
) -> int:
    """TIFF 影像裁剪主入口函数。"""
    input_path = Path(input_path).resolve()
    if not input_path.exists():
        logger.error(f"输入 TIFF 文件不存在: {input_path}")
        return 1
        
    if input_path.suffix.lower() not in (".tif", ".tiff"):
        logger.error("不支持的文件格式，本工具仅支持 TIFF/GeoTIFF 文件。")
        return 1

    if output_dir is None:
        if vector_path is not None:
            output_dir = input_path.parent / f"{input_path.stem}_vector_crops"
        else:
            output_dir = input_path.parent / f"{input_path.stem}_crops"
    else:
        output_dir = Path(output_dir).resolve()
        
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"开始处理 TIFF 影像: {input_path}")
    try:
        with rasterio.open(input_path) as src:
            width = src.width
            height = src.height
            nodata_val = src.nodata
            logger.info(f"源图像规格: {width}x{height}, 波段数: {src.count}, Nodata值: {nodata_val}")
            
            # 模式 C: 按图索骥 (通过矢量文件裁剪)
            if vector_path is not None:
                vector_path = Path(vector_path).resolve()
                if not vector_path.exists():
                    logger.error(f"矢量文件不存在: {vector_path}")
                    return 1
                
                try:
                    import geopandas as gpd
                    from shapely.geometry import box
                    from rasterio.windows import from_bounds
                except ImportError as e:
                    logger.error(f"缺失必要依赖以运行矢量裁剪模式: {e}. 请确保安装了 geo 扩展。")
                    return 1
                    
                try:
                    gdf = gpd.read_file(vector_path)
                except Exception as e:
                    logger.error(f"读取矢量文件失败: {e}")
                    return 1
                    
                if gdf.empty:
                    logger.error("矢量文件没有包含有效的几何要素。")
                    return 1
                    
                # 校验坐标系一致性
                if gdf.crs != src.crs:
                    logger.error(f"坐标系不一致！矢量文件 CRS 为 {gdf.crs}，而 TIFF 影像 CRS 为 {src.crs}。")
                    return 1
                    
                # 校验至少有交集
                img_box = box(*src.bounds)
                intersects_mask = gdf.intersects(img_box)
                gdf_matched = gdf[intersects_mask]
                
                if gdf_matched.empty:
                    logger.error("矢量要素与影像范围没有任何交集，匹配失败。")
                    return 1
                    
                logger.info(f"矢量文件与影像匹配成功。共发现 {len(gdf)} 个要素，其中有 {len(gdf_matched)} 个与图像相交。")
                
                success_count = 0
                for idx, row in gdf_matched.iterrows():
                    geom = row.geometry
                    if geom.is_empty:
                        continue
                        
                    minx, miny, maxx, maxy = geom.bounds
                    win = from_bounds(minx, miny, maxx, maxy, transform=src.transform)
                    win_round = win.round_lengths().round_offsets()
                    img_win = Window(0, 0, width, height)
                    final_win = img_win.intersection(win_round)
                    
                    if final_win.width <= 0 or final_win.height <= 0:
                        logger.warning(f"要素 {idx} 的裁剪窗口无效或在图像范围外，跳过。")
                        continue
                        
                    try:
                        data = src.read(window=final_win)
                        img = numpy_to_rgb_image(data)
                        
                        out_filename = f"{input_path.stem}_crop_{idx}_{final_win.width}x{final_win.height}.jpg"
                        output_path = output_dir / out_filename
                        
                        img.save(output_path, format="JPEG", quality=100)
                        logger.info(f"导出序号 {success_count+1} , 尺寸px: {final_win.width}x{final_win.height}")
                        success_count += 1
                    except Exception as e:
                        logger.error(f"导出要素 {idx} 的裁剪图失败: {e}")
                        
                if success_count == 0:
                    logger.error("未能成功导出任何矢量裁剪样本。")
                    return 1
                logger.info(f"✨ 成功导出 {success_count} 个矢量裁剪样本，保存在: {output_dir}")
                return 0

            # 模式 A & B (原中心裁剪或随机无重叠裁剪)
            if width < size or height < size:
                logger.error(f"图像尺寸 ({width}x{height}) 小于所要求的裁剪大小 ({size}x{size})")
                return 1
                
            selected_windows = []
            
            # 情况 A: 只从中心抠一张图
            if num_crops <= 0:
                col_off = (width - size) // 2
                row_off = (height - size) // 2
                center_window = Window(col_off, row_off, size, size)
                
                # 检查 nodata 占比作为警告或报错
                ratio = get_nodata_ratio(src, center_window, nodata_val)
                logger.info(f"中心裁剪窗口 (col_off={col_off}, row_off={row_off})，检测到 Nodata 占比为: {ratio:.2%}")
                if ratio > nodata_tolerance:
                    logger.warning(f"注意: 中心裁剪区域的 Nodata 占比 ({ratio:.2%}) 超出了阈值限制 ({nodata_tolerance:.2%})。")
                selected_windows.append((center_window, "center"))
            
            # 情况 B: 随机抠 n 张图，保证无重叠且控制 nodata 占比
            else:
                max_attempts = 10000
                attempts = 0
                while len(selected_windows) < num_crops and attempts < max_attempts:
                    attempts += 1
                    col_off = random.randint(0, width - size)
                    row_off = random.randint(0, height - size)
                    temp_window = Window(col_off, row_off, size, size)
                    
                    # 1. 检查重叠
                    overlap = False
                    for win, _ in selected_windows:
                        if check_overlap(temp_window, win):
                            overlap = True
                            break
                    if overlap:
                        continue
                        
                    # 2. 检查 nodata 占比
                    ratio = get_nodata_ratio(src, temp_window, nodata_val)
                    if ratio > nodata_tolerance:
                        continue
                        
                    selected_windows.append((temp_window, str(len(selected_windows) + 1)))
                    logger.debug(f"已选取第 {len(selected_windows)} 个有效候选窗口: col_off={col_off}, row_off={row_off}, Nodata 占比: {ratio:.2%}")
                    
                if len(selected_windows) < num_crops:
                    logger.error(f"在尝试了 {max_attempts} 次随机寻优后，仅能筛选出 {len(selected_windows)} 个满足重叠与 nodata 阈值限制的窗口（数量要求: {num_crops}）。")
                    return 1

            # 执行裁剪与文件物理保存
            for idx_label, (window, suffix) in enumerate(selected_windows, 1):
                out_filename = f"{input_path.stem}_{suffix}.tif"
                output_path = output_dir / out_filename
                logger.info(f"[{idx_label}/{len(selected_windows)}] 正在导出瓦片到: {output_path}...")
                
                new_transform = w_transform(window, src.transform)
                meta = src.meta.copy()
                meta.update({
                    'height': size,
                    'width': size,
                    'transform': new_transform
                })
                
                with rasterio.open(output_path, 'w', **meta) as dst:
                    for i in range(1, src.count + 1):
                        data = src.read(i, window=window)
                        dst.write(data, i)
                        
            logger.info(f"✨ 成功导出所有裁剪样本，保存在: {output_dir}")
            return 0
            
    except Exception as e:
        logger.exception(f"裁剪过程发生异常错误: {e}")
        return 1
