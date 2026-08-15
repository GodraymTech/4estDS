"""业务任务层（tasks/）。

CLI 层（cli.py）与 Worker / API 只负责"解析参数 → 调任务 → 打结果"。
所有实质流程编排（推理、切片、导出、报告、清理等）均在此层实现。
"""
from .infer import run_infer_pipeline

__all__ = ["run_infer_pipeline"]
