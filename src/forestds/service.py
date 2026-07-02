"""应用服务层 (Application Service)。

职责(单一): 把一个 ``InferenceRequest`` 编排成一次完整、可发布的推理作业，
拥有单一的 run 生命周期所有权(start_run_log -> run_infer_pipeline -> promote_run)。

为什么存在(DRY / 防止重复)：
- CLI、Worker、未来 SDK 都需要“开 run_log -> 跑管线 -> 失败收尾 / 成功发布”这套
  生命周期。把它收敛到唯一函数，避免多处拷贝。
- 不依赖 typer / FastAPI / Dramatiq，保持内核与交付方式解耦。
异常策略：捕获管线异常 -> 写 run_log 终态 failed -> 包装为 ``InferenceError`` 上抛，
保留原始异常作为 __cause__，便于上层映射退出码 / HTTP 状态码。
注意: 沿用引擎约定——不对大型推理帧做 repr(log.opt(exception=False))，避免 C 层段错误。
"""
from __future__ import annotations

from typing import Optional

from loguru import logger as log

from .contracts import InferenceRequest, InferenceResult, JobStatus


class InferenceError(RuntimeError):
    """推理作业失败的领域异常，携带 run_id 便于追溯。"""

    def __init__(self, message: str, *, run_id: str, cause: BaseException | None = None):
        super().__init__(message)
        self.run_id = run_id
        self.cause = cause


def run_inference_job(
    request: InferenceRequest,
    *,
    settings=None,
    run_id: Optional[str] = None,
    detector=None,
) -> InferenceResult:
    """执行一次单图推理作业，返回强类型结果。

    Args:
        request: 推理请求 DTO。
        settings: 已加载的 Settings；为 None 时自行 ensure_home + load_settings。
        run_id: 显式指定 run_id；为 None 时自动生成(一作业 = 一 run)。
        detector: 预加载的检测器(Worker 常驻复用)；为 None 时管线内部自建。

    Returns:
        InferenceResult

    Raises:
        InferenceError: 管线任何未捕获异常，已写 run_log 终态 failed。
    """
    from . import paths
    from .config import load_settings
    from .db import writer
    from .logging_setup import new_run_id
    from .tasks.infer import run_infer_pipeline

    if settings is None:
        paths.ensure_home()
        settings = load_settings()

    rid = run_id or new_run_id()
    paths.set_run_context(rid, "infer")
    db_url = settings.get("url", None)
    arch_val = request.arch or settings.get("detect.arch", "ultralytics")

    writer.start_run_log(
        rid,
        "infer",
        model_arch=arch_val,
        input_path=request.image_path,
        params=request.model_dump(mode="json"),
        url=db_url,
    )

    try:
        metrics = run_infer_pipeline(
            request.image_path,
            run_id=rid,
            settings=settings,
            arch=arch_val,
            detector=detector,
            **request.to_pipeline_kwargs(),
        )
    except Exception as exc:  # noqa: BLE001 - 需要兵异常都落 run_log 终态
        writer.finish_run_log(rid, "failed", error=str(exc), url=db_url)
        # 沿用引擎约定: 不让日志框架 repr 推理帧中的大型 numpy 数组(C 层段错误)。
        log.opt(exception=False).error("推理作业失败: run_id={} {} — {}", rid, type(exc).__name__, exc)
        raise InferenceError(str(exc), run_id=rid, cause=exc) from exc

    # 成功后可选发布(规范单木 + 回填 active_run_id)。发布失败不影响已入库的观测。
    published = False
    if request.publish:
        try:
            writer.promote_run(rid, url=db_url)
            published = True
        except Exception as exc:  # noqa: BLE001
            log.warning("发布(promote_run)失败，结果已入库但未激活: run_id={} {}", rid, exc)

    return InferenceResult.from_metrics(metrics, status=JobStatus.succeeded, published=published)
