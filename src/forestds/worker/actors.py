"""Dramatiq actors: GPU 推理作业。

设计要点：
- infer_actor 在进程内常驻缓存 Detector(权重仅加载一次)，GPU 队列 concurrency=1
  (由 worker 启动参数 --processes 1 --threads 1 + queue_name 保证，见 deploy/)。
- 作业与 run_id 一一对应；runs 表即作业状态存储(API 轮询 reader.get_run(run_id))。
- 复用 service.run_inference_job 的统一生命周期(DRY)；不自动重试(GPU 昂贵且非幂等)。
"""
from __future__ import annotations

import os
from typing import Any

import dramatiq
from loguru import logger as log

from . import broker as _broker  # noqa: F401  确保 broker 先于 actor 装配
from ..contracts import BatchInferenceRequest, InferenceRequest
from ..service import InferenceError, run_batch_inference_job, run_inference_job

# GPU 专用队列名；worker 以 --processes 1 --threads 1 消费该队列以实现 concurrency=1。
GPU_QUEUE = os.environ.get("forestds_GPU_QUEUE", "gpu")
REVIEW_GPU_QUEUE = os.environ.get("forestds_REVIEW_GPU_QUEUE", "review_gpu")
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
            device=settings.get("detect.device", settings.get("device", None)),
            verbose=settings.get("detect.verbose", False),
        )
        _detector_cache[arch] = det
        log.info("GPU worker 预热检测器(常驻): arch={}", arch)
    return det


def _setup_actor_logging(settings, run_id: str, task_type: str) -> None:
    """为异步任务安装带 run_id 的日志 sink。GPU 队列单并发，重配全局 logger 可控。"""
    from .. import paths
    from ..logging_setup import setup_logging

    level = str(settings.get("level", "INFO"))
    setup_logging(level=level, run_id=run_id, task_type=task_type, to_file=True)
    paths.set_run_context(run_id, task_type)


@dramatiq.actor(queue_name=GPU_QUEUE, max_retries=0, time_limit=_INFER_TIME_LIMIT_MS)
def infer_actor(run_id: str, request_dict: dict) -> None:
    """单图推理作业(GPU)。参数均为 JSON 可序列化类型。

    状态不在此返回；由 runs 表记录(running/succeeded/failed)，API 轮询获取。
    """
    settings = _get_settings()
    _setup_actor_logging(settings, run_id, "infer")
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
        # 状态已落 runs=failed；不重试(max_retries=0)，吹掉异常避免框架重入。
        log.warning("作业失败已记录: run_id={}", run_id)


@dramatiq.actor(queue_name=GPU_QUEUE, max_retries=0, time_limit=_INFER_TIME_LIMIT_MS)
def batch_actor(run_id: str, request_dict: dict) -> None:
    """批量推理作业(GPU 串行)。"""
    settings = _get_settings()
    _setup_actor_logging(settings, run_id, "batch")
    request = BatchInferenceRequest.model_validate(request_dict)

    try:
        metrics = run_batch_inference_job(request, settings=settings, run_id=run_id)
        log.info(
            "批量作业完成: run_id={} 总数={} 成功={} 失败={} 累计单木={}",
            run_id, metrics.get("total"), metrics.get("succeeded"),
            metrics.get("failed"), metrics.get("total_trees"),
        )
    except InferenceError:
        log.warning("批量作业失败已记录: run_id={}", run_id)


def _run_review_attempt(session_id: str, attempt_id: str, db_url: str | None) -> None:
    settings = _get_settings()
    from ..review.inference_service import ReviewInferenceService, build_review_adapter

    service = ReviewInferenceService(
        db_url,
        tile_size=int(settings.get("review.tile_size", 1024)),
        batch_size=int(settings.get("review.batch_size", 4)),
    )
    try:
        result = service.run_attempt(session_id, attempt_id, adapter=build_review_adapter(settings))
        log.info(
            "复核 attempt 完成: session={} attempt={} candidates={}",
            session_id,
            attempt_id,
            result.get("candidate_count"),
        )
    except Exception as exc:  # noqa: BLE001 - 状态已由服务写入草稿，actor 不重试
        log.warning("复核 attempt 失败: session={} attempt={} error={}", session_id, attempt_id, exc)


@dramatiq.actor(queue_name=REVIEW_GPU_QUEUE, priority=0, max_retries=0, time_limit=_INFER_TIME_LIMIT_MS)
def review_viewport_actor(session_id: str, attempt_id: str, db_url: str | None = None) -> None:
    """短视口任务优先进入 review_gpu。"""
    _run_review_attempt(session_id, attempt_id, db_url)


@dramatiq.actor(queue_name=REVIEW_GPU_QUEUE, priority=10, max_retries=0, time_limit=_INFER_TIME_LIMIT_MS)
def review_full_actor(session_id: str, attempt_id: str, db_url: str | None = None) -> None:
    """整图任务低优先级，仍保持单 GPU 串行。"""
    _run_review_attempt(session_id, attempt_id, db_url)
