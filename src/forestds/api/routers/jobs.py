"""异步推理作业端点。

- POST /jobs/infer -> 202 + job_id(即 run_id)，作业入 GPU 队列异步执行。
- GET  /jobs/:job_id -> 从 run_logs 轮询状态(无行=queued)。

作业状态复用 run_logs 表为单一真相，不引入额外结果后端(KISS/一致性)。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Response, status

from ...contracts import InferenceRequest, JobStatus
from ..deps import get_db_url, get_settings, get_storage_dep
from ..schemas import InferSubmit, JobRef, JobStatusOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post(
    "/infer",
    response_model=JobRef,
    status_code=status.HTTP_202_ACCEPTED,
    summary="提交单图推理作业(异步)",
)
def submit_infer(
    body: InferSubmit,
    response: Response,
    storage=Depends(get_storage_dep),
    settings=Depends(get_settings),
) -> JobRef:
    if not storage.exists(body.image_key):
        raise HTTPException(status_code=404, detail=f"影像对象不存在: {body.image_key}")

    # 把存储 key 解析为 Worker 可读的本地路径(引擎使用 rasterio 窗口读，需本地文件)。
    image_path = storage.local_path(body.image_key)

    # 服务端默认 publish=True：作业成功后发布为地块正式版本(生成规范单木)。
    req = InferenceRequest(
        image_path=image_path,
        arch=body.arch,
        acquisition_time=body.acquisition_time,
        location=body.location,
        tile_size=body.tile_size,
        overlap_rate=body.overlap_rate,
        export_fmt=body.export_fmt,
        publish=True,
    )

    # 延迟 import worker，避免在未配 Redis 的环境导入时即连 broker。
    from ...worker import enqueue_inference

    job_id = enqueue_inference(req)
    response.headers["Location"] = f"/api/v1/jobs/{job_id}"
    return JobRef(job_id=job_id, status=JobStatus.queued)


@router.get("/{job_id}", response_model=JobStatusOut, summary="查询作业状态")
def get_job(job_id: str, db_url: str | None = Depends(get_db_url)) -> JobStatusOut:
    from ...db import reader

    run = reader.get_run(job_id, url=db_url)
    if run is None:
        # 已入队但 Worker 尚未 start_run_log。
        return JobStatusOut(job_id=job_id, status=JobStatus.queued)

    metrics: dict = {}
    raw = run.get("metrics_json")
    if raw:
        try:
            metrics = json.loads(raw)
        except (ValueError, TypeError):
            metrics = {}

    status_val = run.get("status") or "running"
    try:
        job_status = JobStatus(status_val)
    except ValueError:
        job_status = JobStatus.running

    return JobStatusOut(
        job_id=job_id,
        status=job_status,
        tract_id=metrics.get("tract_id"),
        started_at=run.get("started_at"),
        ended_at=run.get("ended_at"),
        duration_s=run.get("duration_s"),
        error=run.get("error"),
        metrics=metrics,
    )
