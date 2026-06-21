"""图像切片保存与坐标回贴命名。

设计原则：
- 支持各种输入格式（TIFF 走 rasterio 窗口读取，JPG/PNG 等走 Pillow 内存读取）。
- 实现自相似/规则切片网格，利用 build_quadtree 与 clamp_window 构建。
- 子图命名采用专利规定的格式：{image_stem}__run_{run_id}__o{x}_{y}__s{tile_size}.jpg。
- 支持从 cli.py 中完全剥离底层文件操作，符合工业级解耦规范。
"""
from __future__ import annotations

import os
from pathlib import Path
from loguru import logger as log

try:
    import numpy as np
    from PIL import Image
except ImportError:
    np = None
    Image = None

from ..engine.sources import RasterImageSource
from ..preprocess.slicing import generate_slice_windows


def execute_slicing(
    image_path: str | Path,
    out_dir: str | Path | None,
    tile_size: int,
    overlap_rate: float,
    run_id: str = "preprocess",
    save_quality: int = 95,
) -> int:
    """对影像进行切割并落盘子图，返回成功保存的瓦片数。
    
    瓦片命名格式: {image_stem}__run_{run_id}__o{x}_{y}__s{tile_size}.jpg
    """
    if Image is None or np is None:
        log.error("缺少 Pillow 或 numpy，无法执行静态切片落盘。")
        return 0

    path = Path(image_path)
    if not path.exists():
        log.error(f"影像不存在: {path}")
        return 0

    image_stem = path.stem
    is_tiff = path.suffix.lower() in (".tif", ".tiff")

    # 确定输出路径，将 {image_stem}__run_{run_id} 作为父目录插在尾部
    if out_dir is None:
        from .. import paths
        base_out = paths.outputs_preprocess_dir()
    else:
        base_out = Path(out_dir)
    out_path = base_out / f"tiles__{image_stem}"

    out_path.mkdir(parents=True, exist_ok=True)

    # 1. 打开数据源获取宽高与像素数据获取器
    source = None
    pil_arr = None
    width, height = 0, 0

    try:
        if is_tiff:
            try:
                source = RasterImageSource(str(path))
                width = source.width
                height = source.height
            except Exception as e:
                log.warning(f"rasterio 窗口打开失败，回退 Pillow 载入: {e}")
        
        if source is None:
            # 使用 Pillow 读入整图
            with Image.open(path) as img:
                img_rgb = img.convert("RGB")
                pil_arr = np.asarray(img_rgb)
                height, width = pil_arr.shape[:2]
    except Exception as e:
        log.error(f"初始化图像数据源失败: {e}")
        return 0

    # 2. 调用预处理公共切片清单生成，拒绝推理/切片重复造轮子
    windows = generate_slice_windows(width, height, tile_size, overlap_rate)
    log.info(
        f"开始切片: 图像={path.name} ({width}x{height}), "
        f"瓦片={tile_size}px, 重叠率={overlap_rate:.0%}, "
        f"预计数量={len(windows)} 块"
    )

    saved_count = 0

    try:
        from tqdm import tqdm
        for (wx, wy, w, h) in tqdm(windows, desc="切片落盘中", ncols=80, leave=False):

                # 3. 获取局部像素
                pixels = None
                if source is not None:
                    pixels = source.read_window(wx, wy, w, h)
                elif pil_arr is not None:
                    pixels = pil_arr[wy:wy + h, wx:wx + w, :]

                if pixels is None:
                    continue

                # 4. 保存为 JPG 并按照像素回贴格式命名
                # {image_stem}__run_{run_id}__o{gx}_{gy}__s{tile_size}.jpg
                tile_img = Image.fromarray(pixels)
                tile_name = f"o{wx}_{wy}__s{tile_size}.jpg"
                tile_file = out_path / tile_name
                
                # 使用指定品质 JPEG 保存
                tile_img.save(tile_file, "JPEG", quality=save_quality)
                saved_count += 1

    except Exception as e:
        log.exception(f"静态切片落盘时发生异常: {e}")
    finally:
        if source is not None:
            try:
                source.close()
            except Exception:
                pass

    log.info(f"{saved_count} 块切片导出成功！")
    return saved_count
