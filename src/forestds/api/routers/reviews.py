"""单 TIFF 智能复核 HTTP 边界。"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ...review import (
    ReviewConflict,
    ReviewError,
    ReviewNotFound,
    ReviewPublishService,
    ReviewSessionService,
)
from ..deps import get_db_url
from ..schemas import (
    ReviewCancelCommand,
    ReviewCreate,
    ReviewOperationBatch,
    ReviewPatchOut,
    ReviewPublishOut,
    ReviewRevisionCommand,
    ReviewSessionOut,
    ReviewWorkspaceOut,
)

router = APIRouter(prefix="/reviews", tags=["reviews"])


def _http_error(exc: ReviewError) -> HTTPException:
    if isinstance(exc, ReviewNotFound):
        status = 404
    elif isinstance(exc, ReviewConflict):
        status = 409
    else:
        status = 422
    return HTTPException(status_code=status, detail=exc.as_detail())


def _session_out(value) -> ReviewSessionOut:
    data = asdict(value)
    data.pop("draft_path", None)
    return ReviewSessionOut(**data)


@router.get("", response_model=list[ReviewSessionOut], summary="复核会话列表")
def list_reviews(
    status: str | None = Query(None),
    db_url: str | None = Depends(get_db_url),
) -> list[ReviewSessionOut]:
    return [_session_out(item) for item in ReviewSessionService(db_url).list(status=status)]


@router.post("", response_model=ReviewSessionOut, summary="创建单 TIFF 复核会话")
def create_review(body: ReviewCreate, db_url: str | None = Depends(get_db_url)) -> ReviewSessionOut:
    try:
        value = ReviewSessionService(db_url).create(body.phase_id, body.tiff_id, body.mode, body.base_run_id)
        return _session_out(value)
    except ReviewError as exc:
        raise _http_error(exc) from exc


@router.get("/{session_id}", response_model=ReviewSessionOut, summary="复核会话详情")
def get_review(session_id: str, db_url: str | None = Depends(get_db_url)) -> ReviewSessionOut:
    try:
        return _session_out(ReviewSessionService(db_url).get(session_id))
    except ReviewError as exc:
        raise _http_error(exc) from exc


@router.get("/{session_id}/workspace", response_model=ReviewWorkspaceOut, summary="恢复复核工作集")
def get_review_workspace(session_id: str, db_url: str | None = Depends(get_db_url)) -> ReviewWorkspaceOut:
    try:
        value = ReviewSessionService(db_url).workspace(session_id)
        return ReviewWorkspaceOut(**value.as_dict())
    except ReviewError as exc:
        raise _http_error(exc) from exc


@router.get("/{session_id}/preview", summary="复核 TIFF 低分辨率预览")
def get_review_preview(
    session_id: str,
    max_size: int = Query(1600, ge=256, le=2400),
    db_url: str | None = Depends(get_db_url),
) -> Response:
    """浏览器只接收降采样预览，不读取完整 TIFF。"""
    try:
        session = ReviewSessionService(db_url).get(session_id)
        from .tiles import _resolve_tiff_image_path

        path = _resolve_tiff_image_path(session.phase_id, session.tiff_id, db_url)
        import numpy as np
        import rasterio
        from PIL import Image
        from io import BytesIO
        from rasterio.enums import Resampling

        with rasterio.open(path) as source:
            scale = min(1.0, max_size / max(source.width, source.height))
            width = max(1, round(source.width * scale))
            height = max(1, round(source.height * scale))
            bands = list(range(1, min(source.count, 3) + 1))
            data = source.read(bands, out_shape=(len(bands), height, width), resampling=Resampling.bilinear)
        if data.shape[0] == 1:
            data = np.repeat(data, 3, axis=0)
        data = np.moveaxis(data[:3], 0, -1).astype("float32")
        low, high = np.nanpercentile(data, [2, 98])
        if high > low:
            data = (data - low) * (255.0 / (high - low))
        image = Image.fromarray(np.clip(data, 0, 255).astype("uint8"), mode="RGB")
        output = BytesIO()
        image.save(output, format="JPEG", quality=86, optimize=True)
        return Response(output.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=60"})
    except ReviewError as exc:
        raise _http_error(exc) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="TIFF 文件不可访问。") from exc


@router.post("/{session_id}/operations", response_model=ReviewPatchOut, summary="应用复核操作")
def apply_review_operations(
    session_id: str,
    body: ReviewOperationBatch,
    db_url: str | None = Depends(get_db_url),
) -> ReviewPatchOut:
    try:
        patch = ReviewSessionService(db_url).apply_operations(
            session_id, body.revision, body.operation_id, body.operations
        )
        return ReviewPatchOut(**asdict(patch))
    except ReviewError as exc:
        raise _http_error(exc) from exc


@router.post("/{session_id}/undo", response_model=ReviewPatchOut, summary="撤销复核操作")
def undo_review(
    session_id: str,
    body: ReviewRevisionCommand,
    db_url: str | None = Depends(get_db_url),
) -> ReviewPatchOut:
    try:
        return ReviewPatchOut(**asdict(ReviewSessionService(db_url).undo(session_id, body.revision, body.operation_id)))
    except ReviewError as exc:
        raise _http_error(exc) from exc


@router.post("/{session_id}/redo", response_model=ReviewPatchOut, summary="重做复核操作")
def redo_review(
    session_id: str,
    body: ReviewRevisionCommand,
    db_url: str | None = Depends(get_db_url),
) -> ReviewPatchOut:
    try:
        return ReviewPatchOut(**asdict(ReviewSessionService(db_url).redo(session_id, body.revision, body.operation_id)))
    except ReviewError as exc:
        raise _http_error(exc) from exc


@router.post("/{session_id}/publish", response_model=ReviewPublishOut, summary="原子发布复核结果")
def publish_review(session_id: str, db_url: str | None = Depends(get_db_url)) -> ReviewPublishOut:
    try:
        return ReviewPublishOut(**ReviewPublishService(db_url).publish(session_id))
    except ReviewError as exc:
        raise _http_error(exc) from exc


@router.post("/{session_id}/cancel", response_model=ReviewSessionOut, summary="取消复核会话")
def cancel_review(
    session_id: str,
    body: ReviewCancelCommand,
    db_url: str | None = Depends(get_db_url),
) -> ReviewSessionOut:
    try:
        return _session_out(ReviewSessionService(db_url).cancel(session_id, body.revision))
    except ReviewError as exc:
        raise _http_error(exc) from exc
