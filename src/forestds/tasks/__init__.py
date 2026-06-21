"""业务任务层（tasks/）。

CLI 层（cli.py）只负责"解析参数 → 调任务 → 打结果"三件事。
所有实质流程编排（推理、导出、报告、清理等）均在此层实现，与 CLI 解耦，
可被单测、批处理脚本、SDK 直接调用，不依赖 typer/click。
"""
from .infer import run_infer_pipeline
from .batch import run_batch_pipeline

