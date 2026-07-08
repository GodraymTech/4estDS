"""异步推理作业端点。

- POST /jobs/infer -> 202 + job_id(即 run_id)，作业入 GPU 队列异步执行。
- GET  /jobs/:job_id -> 从 runs 轮询状态(无行=queued)。

作业状态复用 runs 表为单一真相，不引入额外结果后端(KISS/一致性)。
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse, PlainTextResponse

from ...contracts import BatchInferenceRequest, InferenceRequest, JobStatus
from ...utils.input_inspect import (
    inspect_input_path,
    normalize_user_path,
    resolve_optional_user_path,
)
from ..deps import get_db_url, get_storage_dep
from ..schemas import (
    CancelAllJobsOut,
    CancelJobOut,
    ArtifactExportOut,
    ArtifactExportRequest,
    ArtifactNode,
    ArtifactTreeOut,
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
            tract_id=row.get("tract_id"),
            geo_area=row.get("geo_area"),
            area_unit=row.get("area_unit"),
            observation_count=int(row.get("observation_count") or 0),
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
    suggested_tract_id = None
    suggested_phase_id = None
    if kind == "file" and first is not None:
        suggested_tract_id = first.stem
        suggested_phase_id = first.phase_id

    return InputInspectOut(
        input_path=body.input_path,
        normalized_path=str(normalized_path),
        input_kind=kind,
        image_count=len(images),
        suggested_tract_id=suggested_tract_id,
        suggested_phase_id=suggested_phase_id,
        images=[
            InputInspectImage(
                path=item.path,
                stem=item.stem,
                width=item.width,
                height=item.height,
                crs_epsg=item.crs_epsg,
                phase_id=item.phase_id,
                phase_source=item.phase_source,
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
            phase_id=body.phase_id,
            tract_id=body.tract_id,
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
                phase_id=body.phase_id,
                tract_id=body.tract_id,
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
                phase_id=body.phase_id,
                tract_id=body.tract_id,
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


@router.post("/cancel-all", response_model=CancelAllJobsOut, summary="终止全部推理作业")
def cancel_all_jobs(db_url: str | None = Depends(get_db_url)) -> CancelAllJobsOut:
    from ...cancellation import request_cancel
    from ...db import reader, writer
    from ...worker.broker import broker
    from ...worker.actors import GPU_QUEUE

    purged: list[str] = []
    try:
        broker.flush(GPU_QUEUE)
        purged.append(GPU_QUEUE)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"清空推理队列失败: {exc}") from exc

    cancelled = 0
    for row in reader.list_runs(url=db_url, limit=200):
        if row.get("task_type") not in {"infer", "batch"}:
            continue
        if _job_status(row.get("status")) not in {JobStatus.queued, JobStatus.running}:
            continue
        run_id = str(row["run_id"])
        request_cancel(run_id)
        writer.finish_run_log(
            run_id,
            "failed",
            url=db_url,
            metrics=_metrics_from_run(row),
            duration_s=row.get("duration_s"),
            error="用户一键终止全部推理作业",
        )
        cancelled += 1

    return CancelAllJobsOut(
        cancelled=cancelled,
        purged_queues=purged,
        message=f"已终止全部推理作业：清空队列 {', '.join(purged)}，标记 {cancelled} 个运行中/排队作业",
    )


@router.get("/{job_id}/artifacts", response_model=ArtifactTreeOut, summary="读取运行成果目录树")
def get_artifacts(job_id: str) -> ArtifactTreeOut:
    from ... import paths

    run_dir = paths.find_run_dir(job_id, "infer")
    if run_dir is None:
        return ArtifactTreeOut(run_id=job_id, available=False)
    return ArtifactTreeOut(
        run_id=job_id,
        run_dir=str(run_dir),
        available=True,
        tree=_artifact_nodes(run_dir, run_dir),
    )


@router.get("/{job_id}/artifacts/file", summary="预览运行成果文件")
def preview_artifact(job_id: str, path: str = Query(...)) -> Response:
    root = _require_run_dir(job_id)
    target = _safe_artifact_path(root, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    suffix = target.suffix.lower()
    if suffix in {".txt", ".log", ".md", ".csv", ".json", ".geojson", ".xml", ".prj", ".cpg"}:
        return PlainTextResponse(target.read_text(encoding="utf-8", errors="replace"))
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf"}:
        return FileResponse(target)
    raise HTTPException(status_code=415, detail="该文件类型暂不支持浏览器预览，请使用选择导出")


@router.post("/{job_id}/artifacts/export", response_model=ArtifactExportOut, summary="打包选择的运行成果")
def export_artifacts(job_id: str, body: ArtifactExportRequest) -> ArtifactExportOut:
    root = _require_run_dir(job_id)
    selected = body.paths or ["."]
    zip_dir = root / "exports"
    zip_dir.mkdir(exist_ok=True)
    zip_path = zip_dir / f"{job_id}_selected_artifacts.zip"
    added: set[str] = set()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in selected:
            target = _safe_artifact_path(root, rel)
            if _is_ignored_artifact(root, target):
                continue
            if target.is_dir():
                for child in target.rglob("*"):
                    if child.is_file() and not _is_ignored_artifact(root, child):
                        arcname = str(child.relative_to(root))
                        if arcname not in added:
                            zf.write(child, arcname)
                            added.add(arcname)
            elif target.is_file():
                arcname = str(target.relative_to(root))
                if arcname not in added:
                    zf.write(target, arcname)
                    added.add(arcname)
    return ArtifactExportOut(
        run_id=job_id,
        filename=zip_path.name,
        url=f"/api/v1/jobs/{job_id}/artifacts/download?path={zip_path.relative_to(root)}",
    )


@router.get("/{job_id}/artifacts/download", summary="下载已打包成果")
def download_artifact(job_id: str, path: str = Query(...)) -> FileResponse:
    root = _require_run_dir(job_id)
    target = _safe_artifact_path(root, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(target, filename=target.name)


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
    formatted_matches = sorted(p for p in logs_dir.glob(f"*__{job_id}__*.log") if not p.name.endswith(".ui.log"))
    if formatted_matches:
        return formatted_matches[-1]
    raw_matches = sorted(logs_dir.glob(f"*__{job_id}__*.ui.log"))
    if raw_matches:
        return raw_matches[-1]
    return None


def _strip_log_prefix(line: str) -> str:
    return _FORMAT_PREFIX_RE.sub("", line)


_PREVIEW_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf",
    ".txt", ".log", ".md", ".csv", ".json", ".geojson", ".xml", ".prj", ".cpg",
}

_TOP_DESCRIPTIONS = {
    "multisource": "多源融合成果：点云/DSM/DEM 生成的高程热力图、剖面图、等高线和矢量结果。",
    "reports": "报告成果：Markdown 原始报告、PDF 正式报告与报告图表资源。",
    "vectors_bbox": "空间矢量成果：最终单木检测框/冠幅的 GIS 图层文件。",
}


def _require_run_dir(job_id: str) -> Path:
    from ... import paths

    run_dir = paths.find_run_dir(job_id, "infer")
    if run_dir is None:
        raise HTTPException(status_code=404, detail=f"未找到运行成果目录: {job_id}")
    return run_dir


def _safe_artifact_path(root: Path, rel: str) -> Path:
    candidate = (root / rel).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise HTTPException(status_code=400, detail="非法成果路径")
    return candidate


def _is_ignored_artifact(root: Path, path: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    parts = rel.parts
    return bool(parts and parts[0] in {"preprocess", "exports"})


def _artifact_nodes(root: Path, base: Path) -> list[ArtifactNode]:
    nodes: list[ArtifactNode] = []
    for child in sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        if _is_ignored_artifact(root, child):
            continue
        rel = child.relative_to(root)
        suffix = child.suffix.lower()
        node = ArtifactNode(
            key=str(rel),
            name=child.name,
            path=str(rel),
            type="directory" if child.is_dir() else "file",
            size=child.stat().st_size if child.is_file() else None,
            previewable=child.is_file() and suffix in _PREVIEW_SUFFIXES,
            description=_TOP_DESCRIPTIONS.get(child.name) if base == root else None,
            children=_artifact_nodes(root, child) if child.is_dir() else [],
        )
        nodes.append(node)
    return nodes
