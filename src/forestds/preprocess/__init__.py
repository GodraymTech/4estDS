"""推理流水线的第一环 -- 预处理层:超大 GeoTIFF 自适应切片(创新点 A)。"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .pipeline import prepare_inference_image

__all__ = ["prepare_inference_image"]


def __getattr__(name: str):
    if name == "prepare_inference_image":
        from .pipeline import prepare_inference_image

        return prepare_inference_image
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
