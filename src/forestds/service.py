"""业务外观层 (Facade / Application Service)。

职责(单一): 编排核心管线、状态写回与错误映射，为 Worker / API / CLI 提供开箱即用的业务方法。
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

from loguru import logger as log

from .contracts import InferenceRequest


class InferenceError(Exception):
    """推理执行异常，携带 run_id 与根因。"""

    def __init__(self, message: str, *, run_id: str | None = None, cause: Exception | None = None):
        super().__init__(message)
        self.run_id = run_id
        self.cause = cause


def run_inference_job(
    request: InferenceRequest,
    *,
    settings: dict | None = None,
    run_id: Optional[str] = None,
    detector_factory: Optional[Callable[[str], Any]] = None,
) -> dict:
    """执行单个影像的完整推理管线，包含状态日志管理与指标写回。"""
    from . import paths
    from .cancellation import JobCancelled, clear_cancel, unlink_cancel
    from .config import load_settings
    from .db import writer
    from .logging_setup import new_run_id
    from .tasks.infer import run_infer_pipeline

    if settings is None:
        paths.ensure_home()
        settings = load_settings()

    arch_val = request.arch or settings.get("detect.arch", "ultralytics")
    rid = run_id or new_run_id()
    paths.set_run_context(rid, "infer")
    db_url = settings.get("url", None)

    writer.start_run_log(
        rid,
        "infer",
        model_arch=arch_val,
        input_path=request.image_path,
        params=request.model_dump(mode="json"),
        url=db_url,
    )

    detector = detector_factory(arch_val) if detector_factory else None
    t0 = time.time()

    try:
        res = run_infer_pipeline(
            request.image_path,
            run_id=rid,
            settings=settings,
            arch=arch_val,
            detector=detector,
            phase_id=request.phase_id,
            tract_id=request.tract_id,
            tile_size=request.tile_size,
            overlap_rate=request.overlap_rate,
            chm=request.chm,
            dsm=request.dsm,
            dem=request.dem,
            las=request.las,
            las_grid_size=request.las_grid_size,
            dem_default=request.dem_default,
            draw_box=request.draw_box,
            export_fmt=request.export_fmt,
        )
        if request.publish:
            try:
                writer.promote_run(rid, url=db_url)
            except Exception as promote_err:
                log.warning("发布失败，结果已入库但未激活: run_id={} {}", rid, promote_err)
        return res
    except JobCancelled as exc:
        writer.finish_run_log(rid, "failed", error=str(exc), duration_s=time.time() - t0, url=db_url)
        log.warning("推理作业被用户终止: run_id={} {}", rid, exc)
        raise InferenceError(str(exc), run_id=rid, cause=exc) from exc
    except Exception as exc:
        writer.finish_run_log(rid, "failed", error=str(exc), duration_s=time.time() - t0, url=db_url)
        log.opt(exception=False).error("推理作业失败: run_id={} {} — {}", rid, type(exc).__name__, exc)
        raise InferenceError(str(exc), run_id=rid, cause=exc) from exc
    finally:
        clear_cancel(rid)
        unlink_cancel(rid)


def run_batch_inference_job(
    request,
    *,
    settings=None,
    run_id: Optional[str] = None,
    detector_factory=None,
) -> dict:
    """兼容别名：提取单项转发给 run_inference_job。"""
    items = getattr(request, "items", None)
    if isinstance(items, list) and items:
        return run_inference_job(
            items[0],
            settings=settings,
            run_id=run_id,
            detector_factory=detector_factory,
        )
    if isinstance(request, InferenceRequest):
        return run_inference_job(
            request,
            settings=settings,
            run_id=run_id,
            detector_factory=detector_factory,
        )
    raise ValueError("无法解析推理请求")


__all__ = ["run_inference_job", "run_batch_inference_job"]
