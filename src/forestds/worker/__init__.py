"""异步任务层 (Dramatiq + Redis)。

职责：把耗时的 GPU 推理作业从 HTTP 请求中剔除，异步执行。
- broker.py: Redis broker 装配。
- actors.py: batch_actor(GPU 队列, concurrency=1, 模型常驻)。
- enqueue_batch_inference: 供 API 层投递推理作业的**唯一**入口。

推理作业只有一种形态：一串各自携带参数的待命项。单图推理即长度为 1 的批量，
因此不存在第二个投递入口。

作业状态不额外存储：复用 runs 表(run_id 即 job_id)。API 轮询 reader.get_run(run_id):
无行=queued，否则取 status(running/succeeded/failed/canceled)。
"""
from __future__ import annotations

from ..contracts import BatchInferenceRequest
from ..logging_setup import new_run_id


def enqueue_batch_inference(request: BatchInferenceRequest) -> str:
    """投递一个推理作业(含 1~N 条待命项)。返回顶层 run_id(即 job_id)。

    延迟 import actors，避免在未配置 Redis 的环境(如纯本地 CLI)导入时即连接 broker。
    """
    from .actors import batch_actor
    from .control import ensure_local_worker

    ensure_local_worker()
    run_id = new_run_id()
    batch_actor.send(run_id, request.model_dump(mode="json"))
    return run_id


__all__ = ["enqueue_batch_inference"]
