"""单 TIFF 智能复核 HTTP 边界。"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Mapping, Sequence
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ...review.session_service import _connect

from ...review import (
    ReviewConflict,
    ReviewError,
    ReviewNotFound,
    ReviewPublishService,
    ReviewSessionService,
    ReviewValidationError,
)
from ..deps import get_db_url
from ..schemas import (
    ReviewCancelCommand,
    ReviewAttemptApply,
    ReviewAttemptCreate,
    ReviewAttemptExpand,
    ReviewAttemptOut,
    ReviewCreate,
    ReviewMaskOperation,
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


def _image_stem(value: str | None) -> str | None:
    return Path(value).stem if value else None


def _load_session_assets(
    db_url: str | None,
    keys: Sequence[tuple[str, str]],
) -> dict[tuple[str, str], dict[str, str | None]]:
    """批量回填会话对应的影像资产展示字段（市县·地块·影像名）。"""
    if not keys:
        return {}
    unique = list(dict.fromkeys(keys))
    values_sql = ",".join("(?,?)" for _ in unique)
    params = [value for key in unique for value in key]
    conn = _connect(db_url)
    try:
        rows = conn.execute(
            "WITH requested(phase_id, tiff_id) AS (VALUES " + values_sql + ") "
            "SELECT requested.phase_id, requested.tiff_id, "
            "       COALESCE(t.file_name, t.tiff_id) AS image_name, "
            "       tr.city AS city, COALESCE(tp.tract_id, tr.tract_id) AS tract_id "
            "FROM requested "
            "JOIN tiffs t ON t.phase_id=requested.phase_id AND t.tiff_id=requested.tiff_id "
            "LEFT JOIN tract_phases tp ON tp.tract_phase_pk=t.tract_phase_pk "
            "LEFT JOIN tracts tr ON tr.tract_pk=tp.tract_pk",
            params,
        ).fetchall()
        return {
            (row["phase_id"], row["tiff_id"]): {
                "image_name": _image_stem(row["image_name"]),
                "city": row["city"],
                "tract_id": row["tract_id"],
            }
            for row in rows
        }
    finally:
        conn.close()


def _session_out(
    value,
    db_url: str | None = None,
    assets: Mapping[tuple[str, str], Mapping[str, str | None]] | None = None,
) -> ReviewSessionOut:
    data = asdict(value)
    data.pop("draft_path", None)
    key = (value.phase_id, value.tiff_id)
    resolved = assets if assets is not None else _load_session_assets(db_url, [key])
    data.update(resolved.get(key) or {})
    return ReviewSessionOut(**data)


@router.get("", response_model=list[ReviewSessionOut], summary="复核会话列表")
def list_reviews(
    status: str | None = Query(None),
    db_url: str | None = Depends(get_db_url),
) -> list[ReviewSessionOut]:
    sessions = ReviewSessionService(db_url).list(status=status)
    assets = _load_session_assets(db_url, [(item.phase_id, item.tiff_id) for item in sessions])
    return [_session_out(item, db_url, assets) for item in sessions]


@router.post("", response_model=ReviewSessionOut, summary="创建单 TIFF 复核会话")
def create_review(body: ReviewCreate, db_url: str | None = Depends(get_db_url)) -> ReviewSessionOut:
    try:
        value = ReviewSessionService(db_url).create(body.phase_id, body.tiff_id, body.mode, body.base_run_id)
        return _session_out(value, db_url)
    except ReviewError as exc:
        raise _http_error(exc) from exc


@router.get("/capabilities", summary="复核模型能力")
def review_capabilities() -> dict:
    from ...config import load_settings
    from ...review.inference_service import build_review_adapter

    settings = load_settings()
    capabilities = dict(build_review_adapter(settings).capabilities())
    scope = str(settings.get("review.default_scope", "region"))
    merge_mode = str(settings.get("review.default_merge_mode", "append"))
    capabilities["defaults"] = {
        "scope": scope if scope in {"region", "full"} else "region",
        "merge_mode": merge_mode if merge_mode in {"append", "replace_all"} else "append",
        "threshold": max(0.0, min(1.0, float(settings.get("review.conf_threshold", 0.25)))),
    }
    capabilities["limits"] = {
        "viewport_max_windows": max(1, int(settings.get("review.viewport_max_windows", 256))),
        "max_candidates_per_attempt": max(1, int(settings.get("review.max_candidates_per_attempt", 50_000))),
        "bbox_page_size": max(100, int(settings.get("review.bbox_page_size", 5_000))),
    }
    return capabilities


@router.get("/{session_id}", response_model=ReviewSessionOut, summary="复核会话详情")
def get_review(session_id: str, db_url: str | None = Depends(get_db_url)) -> ReviewSessionOut:
    try:
        return _session_out(ReviewSessionService(db_url).get(session_id), db_url)
    except ReviewError as exc:
        raise _http_error(exc) from exc


@router.delete("/{session_id}", summary="真删除复核会话")
def delete_review(session_id: str, db_url: str | None = Depends(get_db_url)) -> dict[str, str]:
    try:
        ReviewSessionService(db_url).delete(session_id)
        return {"session_id": session_id, "status": "deleted"}
    except ReviewError as exc:
        raise _http_error(exc) from exc


@router.get("/{session_id}/workspace", response_model=ReviewWorkspaceOut, summary="恢复复核工作集")
def get_review_workspace(
    session_id: str,
    bbox: str | None = Query(None, description="可选 TIFF 像素 bbox: x1,y1,x2,y2"),
    offset: int = Query(0, ge=0),
    limit: int | None = Query(None, ge=1, le=50_000),
    db_url: str | None = Depends(get_db_url),
) -> ReviewWorkspaceOut:
    try:
        value = ReviewSessionService(db_url).workspace(session_id)
        data = value.as_dict()
        items = list(value.items)
        total_items = len(items)
        if bbox:
            try:
                bounds = [float(part) for part in bbox.split(",")]
            except ValueError as exc:
                raise ReviewValidationError("bbox 必须是 4 个数字。", code="invalid_bbox") from exc
            if len(bounds) != 4 or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
                raise ReviewValidationError("bbox 必须是有效的 x1,y1,x2,y2。", code="invalid_bbox")
            items = [
                item for item in items
                if len(item.get("box_px") or []) == 4
                and bounds[0] <= (float(item["box_px"][0]) + float(item["box_px"][2])) / 2 <= bounds[2]
                and bounds[1] <= (float(item["box_px"][1]) + float(item["box_px"][3])) / 2 <= bounds[3]
            ]
            if limit is None:
                from ...config import load_settings

                limit = max(100, int(load_settings().get("review.bbox_page_size", 5_000)))
        data["items"] = items[offset:offset + limit] if limit is not None else items[offset:]
        data["total_items"] = total_items
        data["page_offset"] = offset
        data["page_limit"] = limit
        return ReviewWorkspaceOut(**data)
    except ReviewError as exc:
        raise _http_error(exc) from exc


@router.get("/{session_id}/map-context", summary="复核地图所需 TIFF 与有效区域上下文")
def get_review_map_context(
    session_id: str,
    db_url: str | None = Depends(get_db_url),
) -> dict:
    """一次返回地图初始化所需的稳定元数据，避免前端拼接多个资产查询。"""
    from affine import Affine
    from pyproj import CRS, Transformer

    try:
        session = ReviewSessionService(db_url).get(session_id)
        conn = _connect(db_url)
        try:
            row = conn.execute(
                "SELECT t.pixel_width, t.pixel_height, t.gsd, t.geotransform, t.crs_epsg, t.crs_wkt, "
                "tp.tract_pk, tr.effective_geom, tr.boundary_geom "
                "FROM tiffs t "
                "LEFT JOIN tract_phases tp ON tp.tract_phase_pk=t.tract_phase_pk "
                "LEFT JOIN tracts tr ON tr.tract_pk=tp.tract_pk "
                "WHERE t.phase_id=? AND t.tiff_id=?",
                (session.phase_id, session.tiff_id),
            ).fetchone()
        finally:
            conn.close()
        if row is None or not row["geotransform"] or not (row["crs_epsg"] or row["crs_wkt"]):
            raise ReviewValidationError("TIFF 缺少地图地理参考。", code="missing_georeference")
        transform = Affine(*json.loads(row["geotransform"]))
        crs = CRS.from_epsg(int(row["crs_epsg"])) if row["crs_epsg"] else CRS.from_wkt(row["crs_wkt"])
        converter = None if crs.to_epsg() == 4326 else Transformer.from_crs(crs, 4326, always_xy=True)
        if not row["pixel_width"] or not row["pixel_height"]:
            raise ReviewValidationError("TIFF 缺少像素尺寸。", code="missing_raster_size")
        width, height = int(row["pixel_width"]), int(row["pixel_height"])
        pixel_corners = [(0.0, 0.0), (float(width), 0.0), (float(width), float(height)), (0.0, float(height))]
        native = [transform * point for point in pixel_corners]
        corners = [converter.transform(x, y) for x, y in native] if converter else native
        lng = [point[0] for point in corners]
        lat = [point[1] for point in corners]
        from shapely import wkt
        from shapely.geometry import mapping

        raw_effective = row["effective_geom"] or row["boundary_geom"]
        effective = mapping(wkt.loads(raw_effective)) if raw_effective else None
        gsd = float(row["gsd"] or 0)
        if gsd <= 0:
            from pyproj import Geod

            origin = corners[0]
            one_pixel_native = transform * (1.0, 0.0)
            one_pixel = converter.transform(*one_pixel_native) if converter else one_pixel_native
            _, _, gsd = Geod(ellps="WGS84").inv(origin[0], origin[1], one_pixel[0], one_pixel[1])
        return {
            "phase_id": session.phase_id,
            "tiff_id": session.tiff_id,
            "tract_pk": row["tract_pk"],
            "pixel_width": width,
            "pixel_height": height,
            "gsd": max(float(gsd), 1e-6),
            "bounds_wgs84": [min(lng), min(lat), max(lng), max(lat)],
            "corner_wgs84": [[float(x), float(y)] for x, y in corners],
            "effective_geometry": effective,
        }
    except ReviewError as exc:
        raise _http_error(exc) from exc


@router.post("/{session_id}/attempts", response_model=ReviewAttemptOut, summary="创建并排队交互式 attempt")
def create_review_attempt(
    session_id: str,
    body: ReviewAttemptCreate,
    db_url: str | None = Depends(get_db_url),
) -> ReviewAttemptOut:
    from ...review.inference_service import ReviewInferenceService

    try:
        attempt = ReviewInferenceService(db_url).create_attempt(
            session_id,
            revision=body.revision,
            prompt_type=body.prompt_type,
            prompts=body.prompts,
            visual_exemplars=body.visual_exemplars,
            scope=body.scope.model_dump(),
            merge_mode=body.merge_mode,
            threshold=body.threshold,
        )
        from ...worker.actors import review_full_actor, review_region_actor

        actor = review_region_actor if body.scope.type == "region" else review_full_actor
        actor.send(session_id, attempt["attempt_id"], db_url)
        return ReviewAttemptOut(**attempt)
    except ReviewError as exc:
        raise _http_error(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"code": "review_queue_unavailable", "message": str(exc)}) from exc


@router.get("/{session_id}/attempts/{attempt_id}", response_model=ReviewAttemptOut, summary="attempt 状态")
def get_review_attempt(
    session_id: str,
    attempt_id: str,
    db_url: str | None = Depends(get_db_url),
) -> ReviewAttemptOut:
    from ...review.inference_service import ReviewInferenceService

    try:
        return ReviewAttemptOut(**ReviewInferenceService(db_url).get_attempt(session_id, attempt_id))
    except ReviewError as exc:
        raise _http_error(exc) from exc


@router.post("/{session_id}/attempts/{attempt_id}/cancel", response_model=ReviewAttemptOut, summary="取消 attempt")
def cancel_review_attempt(
    session_id: str,
    attempt_id: str,
    db_url: str | None = Depends(get_db_url),
) -> ReviewAttemptOut:
    from ...review.inference_service import ReviewInferenceService

    try:
        return ReviewAttemptOut(**ReviewInferenceService(db_url).cancel_attempt(session_id, attempt_id))
    except ReviewError as exc:
        raise _http_error(exc) from exc


@router.post("/{session_id}/attempts/{attempt_id}/apply", summary="应用 attempt 候选")
def apply_review_attempt(
    session_id: str,
    attempt_id: str,
    body: ReviewAttemptApply,
    db_url: str | None = Depends(get_db_url),
) -> dict:
    from ...review.inference_service import ReviewInferenceService

    try:
        return ReviewInferenceService(db_url).apply_attempt(
            session_id, attempt_id, revision=body.revision, merge_mode=body.merge_mode
        )
    except ReviewError as exc:
        raise _http_error(exc) from exc


@router.post("/{session_id}/attempts/{attempt_id}/expand", response_model=ReviewAttemptOut, summary="复用参数扩散到全图")
def expand_review_attempt(
    session_id: str,
    attempt_id: str,
    body: ReviewAttemptExpand,
    db_url: str | None = Depends(get_db_url),
) -> ReviewAttemptOut:
    from ...review.inference_service import ReviewInferenceService

    try:
        attempt = ReviewInferenceService(db_url).expand_attempt(session_id, attempt_id, revision=body.revision)
        from ...worker.actors import review_full_actor

        review_full_actor.send(session_id, attempt["attempt_id"], db_url)
        return ReviewAttemptOut(**attempt)
    except ReviewError as exc:
        raise _http_error(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"code": "review_queue_unavailable", "message": str(exc)}) from exc


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


@router.post("/{session_id}/operations/mask", response_model=ReviewPatchOut, summary="编辑实例 mask")
def apply_review_mask_operation(
    session_id: str,
    body: ReviewMaskOperation,
    db_url: str | None = Depends(get_db_url),
) -> ReviewPatchOut:
    try:
        patch = ReviewSessionService(db_url).apply_mask_operation(
            session_id,
            body.revision,
            body.operation_id,
            body.item_id,
            [stroke.model_dump() for stroke in body.strokes],
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
