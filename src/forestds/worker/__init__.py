"""异步任务层 (Dramatiq + Redis)。

职责：把耗时的 GPU 推理作业从 HTTP 请求中剔除，异步执行。
- broker.py: Redis broker 装配。
- actors.py: infer_actor(GPU 队列, concurrency=1, 模型常驻)。
- enqueue_inference: 供 API 层投递单图推理作业的标准入口。

作业状态复用 runs 表 (run_id 即 job_id)。API 轮询 reader.get_run(run_id):
无行=queued，否则取 status(running/succeeded/failed/canceled)。
"""
from __future__ import annotations

from ..contracts import InferenceRequest
from ..logging_setup import new_run_id


def enqueue_inference(request: InferenceRequest) -> str:
    """投递单个影像的推理作业。返回 run_id (即 job_id)。

    延迟 import actors，避免在未配置 Redis 的环境导入时即连接 broker。
    """
    from .actors import infer_actor
    from .control import ensure_local_worker

    ensure_local_worker()
    run_id = new_run_id()
    infer_actor.send(run_id, request.model_dump(mode="json"))
    return run_id


def enqueue_batch_inference(request) -> str:
    """兼容旧接口：提取单图或首项进行标准推理投递。"""
    items = getattr(request, "items", None)
    if isinstance(items, list) and items:
        return enqueue_inference(items[0])
    if isinstance(request, InferenceRequest):
        return enqueue_inference(request)
    raise ValueError("无法解析推理请求条目")


__all__ = ["enqueue_inference", "enqueue_batch_inference"]
