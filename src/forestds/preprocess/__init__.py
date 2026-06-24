"""推理流水线的第一环 -- 预处理层:超大 GeoTIFF 自适应切片(创新点 A)。"""

from .pipeline import prepare_inference_image

__all__ = ["prepare_inference_image"]
