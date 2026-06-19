"""推理编排层(阶段三)。

把切片清单 -> 逐 tile 推理 -> 坐标回写全图 -> WBF 去重 串起来。
"""
from .batch import (
    BatchItemResult,
    BatchResult,
    discover_inputs,
    run_batch,
)
from .runner import (
    InferenceResult,
    run_inference,
)
from .sources import RasterImageSource

__all__ = [
    "BatchItemResult",
    "BatchResult",
    "InferenceResult",
    "RasterImageSource",
    "discover_inputs",
    "run_batch",
    "run_inference",
]
