"""Dramatiq actors: GPU 推理作业。

设计要点：
- infer_actor 在进程内常驻缓存 Detector(权重仅加载一次)，GPU 队列 concurrency=1
  (由 worker 启动参数 --processes 1 --threads 1 + queue_name 保证，见 deploy/)。
- 作业与 run_id 一一对应；run_logs 表即作业状态存储(API 轮询 reader.get_run(run_id))。
- 复用 service.run_inference_job 的统一生命周期(DRY)；不自动重试(GPU 昂贵且非幂等)。
"""
from __future__ import annotations

import os
from typing import Any

import dramatiq
from loguru import logger as log

from . import broker as _broker  # noqa: F401  确保 broker 先于 actor 装配
from ..contracts import InferenceRequest
from ..service import InferenceError, run_inference_job

# GPU 专用队列名；worker 以 --processes 1 --threads 1 消费该队列以实现 concurrency=1。
GPU_QUEUE = os.environ.get("forestds_GPU_QUEUE", "gpu")
# 单作业时限(毫秒)，默认 24h，应对超大 TIFF 的长耗时推理。
_INFER_TIME_LIMIT_MS = int(os.environ.get("forestds_INFER_TIME_LIMIT_MS", str(24 * 60 * 60 * 1000)))

# 进程内缓存(模型常驻) —— 仅在 GPU concurrency=1 前提下安全。
_settings: Any = None
_detector_cache: dict[str, Any] = {}


def _get_settings():
    """进程内缓存 Settings(避免每作业重复加载配置)。"""
    global _settings
    if _settings is None:
        from .. import paths
        from ..config import load_settings

        paths.ensure_home()
        _settings = load_settings()
    return _settings


def _get_detector(arch: str, settings):
    """进程内常驻检测器(权重仅加载一次)，参数与 tasks/batch 保持一致。"""
    det = _detector_cache.get(arch)
    if det is None:
        from ..detect import get_detector

        det = get_detector(
            arch,
            weights=settings.get(f"detect.models.{arch}.weights", settings.get("detect.weights")),
            conf=float(settings.get("detect.conf_threshold", 0.25)),
            iou=float(settings.get("detect.iou_threshold", 0.6)),
            imgsz=int(settings.get("model_input", 1024)),
            device=settings.get("device", None),
            verbose=settings.get("detect.verbose", False),
        )
        _detector_cache[arch] = det
        log.info("GPU worker 预热检测器(常驻): arch={}", arch)
    return det


@dramatiq.actor(queue_name=GPU_QUEUE, max_retries=0, time_limit=_INFER_TIME_LIMIT_MS)
def infer_actor(run_id: str, request_dict: dict) -> None:
    """单图推理作业(GPU)。参数均为 JSON 可序列化类型。

    状态不在此返回；由 run_logs 表记录(running/succeeded/failed)，API 轮询获取。
    """
    settings = _get_settings()
    request = InferenceRequest.model_validate(request_dict)
    arch = request.arch or settings.get("detect.arch", "ultralytics")
    detector = _get_detector(arch, settings)

    try:
        result = run_inference_job(request, settings=settings, run_id=run_id, detector=detector)
        log.info(
            "作业完成: run_id={} tract={} 单木={} 入库={} 发布={}",
            result.run_id, result.tract_id, result.fused_count,
            result.observations_written, result.published,
        )
    except InferenceError:
        # 状态已落 run_logs=failed；不重试(max_retries=0)，吹掉异常避免框架重入。
        log.warning("作业失败已记录: run_id={}", run_id)
