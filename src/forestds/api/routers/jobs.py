"""异步推理作业端点。

- POST /jobs/infer -> 202 + job_id(即 run_id)，作业入 GPU 队列异步执行。
- GET  /jobs/:job_id -> 从 run_logs 轮询状态(无行=queued)。

作业状态复用 run_logs 表为单一真相，不引入额外结果后端(KISS/一致性)。
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ...contracts import BatchInferenceRequest, InferenceRequest, JobStatus
from ...utils.input_inspect import (
    inspect_input_path,
    normalize_user_path,
    resolve_optional_user_path,
)
from ..deps import get_db_url, get_storage_dep
from ..schemas import (
    CancelJobOut,
    InferSubmit,
    InputInspectImage,
    InputInspectOut,
    InputInspectRequest,
    JobHistoryItem,
    JobLogsOut,
    JobRef,
    JobStatusOut,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])

_FORMAT_PREFIX_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+\|\s+"
    r"[A-Z]+\s+\|\s+[^|]+\|\s+[^|]+\|\s+"
)


def _metrics_from_run(run: dict) -> dict:
    raw = run.get("metrics_json")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def _job_status(value: str | None) -> JobStatus:
    try:
        return JobStatus(value or "running")
    except ValueError:
        return JobStatus.running


@router.get("", response_model=list[JobHistoryItem], summary="列出作业历史")
def list_jobs(
    task_type: str | None = Query("infer"),
    limit: int = Query(50, ge=1, le=200),
    db_url: str | None = Depends(get_db_url),
) -> list[JobHistoryItem]:
    from ...db import reader

    rows = reader.list_runs(url=db_url, task_type=task_type, limit=limit)
    return [
        JobHistoryItem(
            run_id=row["run_id"],
            task_type=row["task_type"],
            status=_job_status(row.get("status")),
            model_arch=row.get("model_arch"),
            started_at=row.get("started_at"),
            ended_at=row.get("ended_at"),
            duration_s=row.get("duration_s"),
            input_path=row.get("input_path"),
            error=row.get("error"),
            metrics=_metrics_from_run(row),
        )
        for row in rows
    ]


@router.post("/inspect-input", response_model=InputInspectOut, summary="检查推理输入路径")
def inspect_input(body: InputInspectRequest) -> InputInspectOut:
    try:
        kind, normalized_path, images = inspect_input_path(body.input_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    first = images[0] if images else None
    suggested_location = None
    suggested_acquisition_time = None
    if kind == "file" and first is not None:
        suggested_location = first.stem
        suggested_acquisition_time = first.acquisition_time

    return InputInspectOut(
        input_path=body.input_path,
        normalized_path=str(normalized_path),
        input_kind=kind,
        image_count=len(images),
        suggested_location=suggested_location,
        suggested_acquisition_time=suggested_acquisition_time,
        images=[
            InputInspectImage(
                path=item.path,
                stem=item.stem,
                width=item.width,
                height=item.height,
                crs_epsg=item.crs_epsg,
                acquisition_time=item.acquisition_time,
                acquisition_time_source=item.acquisition_time_source,
            )
            for item in images[:50]
        ],
    )


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
) -> JobRef:
    if bool(body.image_key) == bool(body.input_path):
        raise HTTPException(status_code=400, detail="image_key 与 input_path 必须且只能提供一个")

    dsm = _resolve_aux_path(body.dsm, "DSM")
    dem = _resolve_aux_path(body.dem, "DEM")
    las = _resolve_aux_path(body.las, "LAS")

    if body.image_key:
        if not storage.exists(body.image_key):
            raise HTTPException(status_code=404, detail=f"影像对象不存在: {body.image_key}")

        # 把存储 key 解析为 Worker 可读的本地路径(引擎使用 rasterio 窗口读，需本地文件)。
        image_path = storage.local_path(body.image_key)
        req = InferenceRequest(
            image_path=image_path,
            arch=body.arch,
            acquisition_time=body.acquisition_time,
            location=body.location,
            tile_size=body.tile_size,
            overlap_rate=body.overlap_rate,
            dsm=dsm,
            dem=dem,
            las=las,
            export_fmt=body.export_fmt,
            publish=True,
        )

        from ...worker import enqueue_inference

        job_id = enqueue_inference(req)
    else:
        try:
            kind, normalized_path, _images = inspect_input_path(body.input_path or "")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if kind == "directory":
            batch_req = BatchInferenceRequest(
                input_path=str(normalized_path),
                arch=body.arch,
                acquisition_time=body.acquisition_time,
                location=body.location,
                tile_size=body.tile_size,
                overlap_rate=body.overlap_rate,
                dsm=dsm,
                dem=dem,
                las=las,
                export_fmt=body.export_fmt,
                publish=True,
            )
            from ...worker import enqueue_batch_inference

            job_id = enqueue_batch_inference(batch_req)
        else:
            req = InferenceRequest(
                image_path=str(normalized_path),
                arch=body.arch,
                acquisition_time=body.acquisition_time,
                location=body.location,
                tile_size=body.tile_size,
                overlap_rate=body.overlap_rate,
                dsm=dsm,
                dem=dem,
                las=las,
                export_fmt=body.export_fmt,
                publish=True,
            )
            from ...worker import enqueue_inference

            job_id = enqueue_inference(req)

    response.headers["Location"] = f"/api/v1/jobs/{job_id}"
    return JobRef(job_id=job_id, status=JobStatus.queued)


@router.get("/{job_id}/logs", response_model=JobLogsOut, summary="读取作业增量日志")
def get_job_logs(job_id: str, cursor: int = Query(0, ge=0)) -> JobLogsOut:
    log_path = _find_job_log(job_id)
    if log_path is None:
        return JobLogsOut(job_id=job_id, cursor=cursor, lines=[], available=False)

    size = log_path.stat().st_size
    safe_cursor = cursor if cursor <= size else 0
    with log_path.open("r", encoding="utf-8", errors="replace") as f:
        f.seek(safe_cursor)
        text = f.read()
        next_cursor = f.tell()

    lines = [_strip_log_prefix(line) for line in text.splitlines()]
    return JobLogsOut(job_id=job_id, cursor=next_cursor, lines=lines, available=True)


@router.get("/{job_id}", response_model=JobStatusOut, summary="查询作业状态")
def get_job(job_id: str, db_url: str | None = Depends(get_db_url)) -> JobStatusOut:
    from ...db import reader

    run = reader.get_run(job_id, url=db_url)
    if run is None:
        # 已入队但 Worker 尚未 start_run_log。
        return JobStatusOut(job_id=job_id, status=JobStatus.queued)

    metrics = _metrics_from_run(run)
    job_status = _job_status(run.get("status"))

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


@router.post("/{job_id}/cancel", response_model=CancelJobOut, summary="终止推理作业")
def cancel_job(job_id: str, db_url: str | None = Depends(get_db_url)) -> CancelJobOut:
    from ...cancellation import request_cancel
    from ...db import reader, writer

    request_cancel(job_id)
    run = reader.get_run(job_id, url=db_url)
    if run is None:
        return CancelJobOut(job_id=job_id, status=JobStatus.queued, message="已标记取消，若作业尚在队列中将不会继续执行")

    status_val = _job_status(run.get("status"))
    if status_val in (JobStatus.succeeded, JobStatus.failed):
        return CancelJobOut(job_id=job_id, status=status_val, message="作业已结束")

    writer.finish_run_log(
        job_id,
        "failed",
        url=db_url,
        metrics=_metrics_from_run(run),
        duration_s=run.get("duration_s"),
        error="用户请求终止推理作业",
    )
    return CancelJobOut(job_id=job_id, status=JobStatus.failed, message="已请求终止，worker 将在最近检查点停止")


def _resolve_aux_path(raw: str | None, label: str) -> str | None:
    try:
        return resolve_optional_user_path(raw)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"{label} 路径不存在: {normalize_user_path(raw or '')}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{label} 路径无效: {exc}") from exc


def _find_job_log(job_id: str):
    from ... import paths

    logs_dir = paths.logs_dir()
    raw_matches = sorted(logs_dir.glob(f"*__{job_id}__*.ui.log"))
    if raw_matches:
        return raw_matches[-1]
    formatted_matches = sorted(p for p in logs_dir.glob(f"*__{job_id}__*.log") if not p.name.endswith(".ui.log"))
    if formatted_matches:
        return formatted_matches[-1]
    return None


def _strip_log_prefix(line: str) -> str:
    return _FORMAT_PREFIX_RE.sub("", line)
