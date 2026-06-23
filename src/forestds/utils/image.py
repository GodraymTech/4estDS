"""图像/栅格通用工具函数。"""
from __future__ import annotations

from pathlib import Path
from PIL import Image

def get_image_dimensions(image_path: str | Path) -> tuple[int, int]:
    """获取图像的宽和高 (width, height)。
    
    对于 TIFF/GeoTIFF，使用 rasterio 快速读取头信息，防止由于整图加载引发的 OOM。
    对于其他标准图像格式（JPG, PNG 等），使用 PIL.Image.open 读取元数据。
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"影像文件不存在: {path}")

    # 1. 尝试使用 rasterio 快速读取 TIFF 格式的元数据
    if path.suffix.lower() in (".tif", ".tiff"):
        try:
            import rasterio
            with rasterio.open(path) as r_src:
                return r_src.width, r_src.height
        except Exception as e:
            raise ValueError(f"读取影像尺寸失败 {path}: {e}") from e

    # 2. 对于其他格式（或 rasterio 异常时）回退使用 PIL.Image.open 仅读取元数据 (0ms)
    try:
        with Image.open(path) as img:
            return img.size  # 返回 (width, height)
    except Exception as e:
        raise ValueError(f"读取影像尺寸失败 {path}: {e}") from e
