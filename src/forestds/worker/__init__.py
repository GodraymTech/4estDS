"""异步任务层 (Dramatiq + Redis)。

职责：把耗时的 GPU 推理作业从 HTTP 请求中剔离，异步执行。
- broker.py: Redis broker 装配。
- actors.py: infer_actor(GPU 队列, concurrency=1, 模型常驻)。
- enqueue_inference: 供 API 层投递作业的唯一入口。

作业状态不额外存储：复用 run_logs 表(run_id 即 job_id)。API 轮询 reader.get_run(run_id):
无行=queued，否则取 status(running/succeeded/failed)。
"""
from __future__ import annotations

from ..contracts import InferenceRequest
from ..logging_setup import new_run_id


def enqueue_inference(request: InferenceRequest) -> str:
    """投递一个单图推理作业。返回 run_id(即 job_id)。

    延迟 import actors，避免在未配置 Redis 的环境(如纯本地 CLI)导入时即连接 broker。
    """
    from .actors import infer_actor

    run_id = new_run_id()
    infer_actor.send(run_id, request.model_dump(mode="json"))
    return run_id


__all__ = ["enqueue_inference"]
