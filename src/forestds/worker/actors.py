"""Dramatiq actors: GPU 推理作业。

设计要点：
- batch_actor 是推理作业的**唯一** actor：一个作业 = 1~N 条各自携带参数的影像条目，
  单图推理即长度为 1 的批量。
- 进程内常驻缓存 Detector(权重仅加载一次)，GPU 队列 concurrency=1
  (由 worker 启动参数 --processes 1 --threads 1 + queue_name 保证，见 deploy/)。
- 作业与 run_id 一一对应；runs 表即作业状态存储(API 轮询 reader.get_run(run_id))。
- 复用 service.run_batch_inference_job 的统一生命周期(DRY)；不自动重试(GPU 昂贵且非幂等)。
"""
from __future__ import annotations

import os

# 严格锁定底层 OpenMP / MKL / OpenCV 线程数为 1，避免多线程 CUDA/GDAL 内存段错误
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import cv2
cv2.setNumThreads(0)

from typing import Any

import dramatiq
from loguru import logger as log

from . import broker as _broker  # noqa: F401  确保 broker 先于 actor 装配
from ..contracts import InferenceRequest
from ..service import InferenceError

# GPU 专用队列名；worker 以 --processes 1 --threads 1 消费该队列以实现 concurrency=1。
GPU_QUEUE = os.environ.get("forestds_GPU_QUEUE", "gpu")
REVIEW_GPU_QUEUE = os.environ.get("forestds_REVIEW_GPU_QUEUE", "review_gpu")
# 单作业时限(毫秒)，默认 24h，应对超大 TIFF 的长耗时推理。
_INFER_TIME_LIMIT_MS = int(os.environ.get("forestds_INFER_TIME_LIMIT_MS", str(24 * 60 * 60 * 1000)))

import gc
import time

_MODEL_TTL_SECONDS = int(os.environ.get("forestds_MODEL_TTL_SECONDS", "300"))

# 进程内模型独占管理 —— 单 GPU concurrency=1 前提下，确保显存内始终至多驻留 1 个活跃模型。
_settings: Any = None
_detector_cache: dict[str, dict[str, Any]] = {}
_review_adapter_cache: dict[str, dict[str, Any]] = {}


def _cleanup_cuda_cache() -> None:
    """清理 PyTorch CUDA 显存缓存池，将临时激活张量归还给显存驱动。"""
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except (ImportError, Exception):
        pass


def _evict_idle_models(ttl_seconds: int = _MODEL_TTL_SECONDS) -> None:
    """清理空闲时间超过 ttl_seconds 的常驻模型权重，并回收 GPU 显存。"""
    now = time.time()
    expired_detectors = [
        k for k, item in _detector_cache.items()
        if now - item.get("last_used", 0) > ttl_seconds
    ]
    for k in expired_detectors:
        log.info("空闲超时卸载检测器模型: arch={}", k)
        item = _detector_cache.pop(k, None)
        if item and "model" in item:
            det = item["model"]
            if hasattr(det, "model"):
                del det.model
            del det

    expired_adapters = [
        k for k, item in _review_adapter_cache.items()
        if now - item.get("last_used", 0) > ttl_seconds
    ]
    for k in expired_adapters:
        log.info("空闲超时卸载复核适配器模型: key={}", k)
        item = _review_adapter_cache.pop(k, None)
        if item and "model" in item:
            adapter = item["model"]
            if hasattr(adapter, "model"):
                del adapter.model
            del adapter

    if expired_detectors or expired_adapters:
        gc.collect()
        _cleanup_cuda_cache()


def _evict_other_models(target_key: str | None = None) -> None:
    """确保 GPU 显存互斥独占：卸载除 target_key 之外的所有已缓存模型（包括检测器与复核适配器），并立即回收显存。"""
    global _detector_cache, _review_adapter_cache
    evicted = False
    for k in list(_detector_cache.keys()):
        if target_key != f"detect:{k}":
            log.info("互斥卸载批处理检测器模型: arch={}", k)
            item = _detector_cache.pop(k, None)
            if item and "model" in item:
                det = item["model"]
                if hasattr(det, "model"):
                    del det.model
                del det
            evicted = True
    for k in list(_review_adapter_cache.keys()):
        if target_key != f"review:{k}":
            log.info("互斥卸载复核适配器模型: key={}", k)
            item = _review_adapter_cache.pop(k, None)
            if item and "model" in item:
                adapter = item["model"]
                if hasattr(adapter, "model"):
                    del adapter.model
                del adapter
            evicted = True
    if evicted:
        gc.collect()
        _cleanup_cuda_cache()


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
    """进程内常驻检测器(权重按需加载，跨任务互斥)，保证 GPU 独占。"""
    _evict_idle_models()
    _evict_other_models(target_key=f"detect:{arch}")

    item = _detector_cache.get(arch)
    if item is None:
        from ..detect import get_detector

        det = get_detector(
            arch,
            weights=settings.get(f"detect.models.{arch}.weights", settings.get("detect.weights")),
            conf=float(settings.get("detect.conf_threshold", 0.25)),
            iou=float(settings.get("detect.iou_threshold", 0.6)),
            imgsz=int(settings.get("detect.model_input", settings.get("model_input", 1024))),
            device=settings.get("detect.device", settings.get("device", None)),
            verbose=settings.get("detect.verbose", False),
        )
        item = {"model": det, "last_used": time.time()}
        _detector_cache[arch] = item
        log.info("GPU worker 加载检测器(互斥独占): arch={}", arch)
    else:
        item["last_used"] = time.time()
    return item["model"]


def _get_review_adapter(settings, prompt_type: str = "visual"):
    """进程内常驻复核适配器(权重按需加载，排除 tasks 批量推理模型共存)，保证 GPU 独占。"""
    _evict_idle_models()
    if prompt_type == "direct":
        cache_key = "yolo:m07"
        _evict_other_models(target_key=f"review:{cache_key}")
        item = _review_adapter_cache.get(cache_key)
        if item is None:
            from ..review.models.yolo import YOLOReviewAdapter

            weights = (
                settings.get("review.models.yolo.variants.m07.weights")
                or settings.get("review.models.yolo.m07.weights")
                or ".4estDS/models/m07-yolo26x-7d20f-det-2cls-e152_baseTrain15.pt"
            )
            adapter = YOLOReviewAdapter(
                weights,
                device=settings.get("review.device", settings.get("detect.device")),
                conf=float(settings.get("review.conf_threshold", 0.25)),
                imgsz=int(settings.get("review.model_input", 640)),
            )
            item = {"model": adapter, "last_used": time.time()}
            _review_adapter_cache[cache_key] = item
            log.info("GPU worker 加载闭集专家复核适配器(互斥独占): key={}", cache_key)
        else:
            item["last_used"] = time.time()
        return item["model"]

    adapter_str = str(settings.get("review.adapter", "dinov")).strip()
    if "-" in adapter_str:
        name, variant = adapter_str.split("-", 1)
    elif ":" in adapter_str:
        name, variant = adapter_str.split(":", 1)
    else:
        name = adapter_str
        default_variant = "swin_l" if name == "dinov" else ("m07" if name == "yolo" else ("26x-m07" if name == "yoloe" else ""))
        variant = str(
            settings.get("review.variant")
            or settings.get("review.dinov_variant" if name == "dinov" else "review.model_variant")
            or default_variant
        )
    cache_key = f"{name.lower().strip()}:{variant.lower().strip()}"
    _evict_other_models(target_key=f"review:{cache_key}")

    item = _review_adapter_cache.get(cache_key)
    if item is None:
        from ..review.inference_service import build_review_adapter

        adapter = build_review_adapter(settings)
        item = {"model": adapter, "last_used": time.time()}
        _review_adapter_cache[cache_key] = item
        log.info("GPU worker 加载复核适配器(互斥独占): key={}", cache_key)
    else:
        item["last_used"] = time.time()
    return item["model"]


def _setup_actor_logging(settings, run_id: str, task_type: str) -> None:
    """为异步任务安装带 run_id 的日志 sink。GPU 队列单并发，重配全局 logger 可控。"""
    from .. import paths
    from ..logging_setup import setup_logging

    level = str(settings.get("level", "INFO"))
    setup_logging(level=level, run_id=run_id, task_type=task_type, to_file=True)
    paths.set_run_context(run_id, task_type)


@dramatiq.actor(queue_name=GPU_QUEUE, max_retries=0, time_limit=_INFER_TIME_LIMIT_MS)
def infer_actor(run_id: str, request_dict: dict) -> None:
    """单图推理作业(GPU 串行执行)。

    向管线注入进程内常驻的检测器工厂，使同一 arch 的权重在多次推理之间常驻显存。
    """
    settings = _get_settings()
    _setup_actor_logging(settings, run_id, "infer")
    request = InferenceRequest.model_validate(request_dict)

    try:
        from ..service import run_inference_job

        metrics = run_inference_job(
            request,
            settings=settings,
            run_id=run_id,
            detector_factory=lambda arch: _get_detector(arch, settings),
        )
        log.info(
            "推理作业完成: run_id={} 单木数={} 耗时={:.2f}s",
            run_id,
            metrics.get("fused_count") or metrics.get("raw_count") or 0,
            metrics.get("duration_s") or 0.0,
        )
    except InferenceError:
        log.warning("推理作业失败已记录: run_id={}", run_id)
    finally:
        _cleanup_cuda_cache()


@dramatiq.actor(queue_name=GPU_QUEUE, max_retries=0, time_limit=_INFER_TIME_LIMIT_MS)
def batch_actor(run_id: str, request_dict: dict) -> None:
    """兼容别名：直接转发单图执行。"""
    infer_actor(run_id, request_dict)


def _run_review_attempt(session_id: str, attempt_id: str, db_url: str | None) -> None:
    settings = _get_settings()
    from ..review.inference_service import ReviewInferenceService

    service = ReviewInferenceService(
        db_url,
        tile_size=int(settings.get("review.tile_size", 1024)),
        batch_size=int(settings.get("review.batch_size", 4)),
        viewport_max_windows=int(settings.get("review.viewport_max_windows", 256)),
        max_candidates=int(settings.get("review.max_candidates_per_attempt", 50_000)),
        effective_area_cache_size=int(settings.get("effective_area.mask_cache_size", 32)),
    )
    try:
        attempt_obj = service.get_attempt(session_id, attempt_id)
        prompt_type = attempt_obj.get("prompt_type", "visual")
        adapter = _get_review_adapter(settings, prompt_type=prompt_type)
        result = service.run_attempt(session_id, attempt_id, adapter=adapter)
        log.info(
            "复核 attempt 完成: session={} attempt={} candidates={}",
            session_id,
            attempt_id,
            result.get("candidate_count"),
        )
    except Exception as exc:  # noqa: BLE001 - 状态已由服务写入草稿，actor 不重试
        log.warning("复核 attempt 失败: session={} attempt={} error={}", session_id, attempt_id, exc)
    finally:
        _cleanup_cuda_cache()


@dramatiq.actor(queue_name=REVIEW_GPU_QUEUE, priority=0, max_retries=0, time_limit=_INFER_TIME_LIMIT_MS)
def review_region_actor(session_id: str, attempt_id: str, db_url: str | None = None) -> None:
    """局部范围任务优先进入 review_gpu。"""
    _run_review_attempt(session_id, attempt_id, db_url)


@dramatiq.actor(queue_name=REVIEW_GPU_QUEUE, priority=10, max_retries=0, time_limit=_INFER_TIME_LIMIT_MS)
def review_full_actor(session_id: str, attempt_id: str, db_url: str | None = None) -> None:
    """整图任务低优先级，仍保持单 GPU 串行。"""
    _run_review_attempt(session_id, attempt_id, db_url)


@dramatiq.actor(queue_name=GPU_QUEUE, max_retries=0, time_limit=_INFER_TIME_LIMIT_MS)
def convert_cog_actor(input_path: str, db_url: str | None = None) -> None:
    """耗时转 COG 任务(后台异步队列处理)。"""
    from pathlib import Path
    from ..db.schema import get_db_connection
    from ..db.writer import _compute_tiff_metadata
    from ..preprocess.cog import TIFF_COG, calculate_exact_effective_ratio, prepared_cog_path

    path = Path(input_path).expanduser()
    if not path.is_file():
        log.error("转 COG 异步任务失败: 文件不存在 {}", path)
        return

    cog_path, prepared_type = prepared_cog_path(path, force=True)
    if prepared_type == TIFF_COG:
        exact_ratio = calculate_exact_effective_ratio(cog_path)
        tiff_meta = _compute_tiff_metadata(cog_path, phase_id="00000000", tract_phase_pk="dummy")
        if tiff_meta:
            exact_effective_area = None
            if tiff_meta.get("footprint_area_hm2") is not None:
                exact_effective_area = round(tiff_meta["footprint_area_hm2"] * exact_ratio, 4)

            conn = get_db_connection(db_url)
            try:
                conn.execute(
                    """
                    UPDATE tiffs
                    SET tiff_type = ?,
                        file_path = ?,
                        pixel_width = ?,
                        pixel_height = ?,
                        bands = ?,
                        crs_wkt = ?,
                        bounds_wgs84 = ?,
                        boundary_geom = ?,
                        boundary_geom_cent = ?,
                        footprint_area_hm2 = ?,
                        effective_area_hm2 = COALESCE(?, effective_area_hm2),
                        updated_at = datetime('now')
                    WHERE file_path = ? OR file_path = ?
                    """,
                    (
                        "COG",
                        str(cog_path),
                        tiff_meta["pixel_width"],
                        tiff_meta["pixel_height"],
                        tiff_meta["bands"],
                        tiff_meta["crs_wkt"],
                        tiff_meta["bounds_wgs84"],
                        tiff_meta["boundary_geom"],
                        tiff_meta["boundary_geom_cent"],
                        tiff_meta["footprint_area_hm2"],
                        exact_effective_area,
                        str(path),
                        str(cog_path),
                    ),
                )
                conn.commit()
            except Exception as e:
                log.warning("异步转 COG 后更新数据库失败: {}", e)
            finally:
                conn.close()
    log.info("异步转 COG 任务完成: path={} -> cog={}", path, cog_path)
