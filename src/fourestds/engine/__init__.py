"""推理编排层(阶段三)。

把切片清单 -> 逐 tile 推理 -> 坐标回写全图 -> WBF 去重 串起来。
"""
from .runner import (
    InferenceResult,
    SyntheticImageSource,
    run_inference,
)

__all__ = ["InferenceResult", "SyntheticImageSource", "run_inference"]
