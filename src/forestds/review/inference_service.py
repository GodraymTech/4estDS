"""交互式复核 attempt：范围换算、分块推理、进度、取消与候选合并。"""
from __future__ import annotations

import json
import math
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from affine import Affine
from pyproj import CRS, Transformer

from ..db.schema import init_db, resolve_db_path
from .domain import ReviewConflict, ReviewNotFound, ReviewValidationError
from .merge_service import ReviewMergeService, weighted_box_fusion
from .models import MockReviewAdapter, RasterWindow, ReviewModelAdapter
from .models.yoloe import YOLOEReviewAdapter
from .masks import mask_item_fields
from .session_service import ReviewSessionService


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def viewport_to_pixel_window(
    bounds_wgs84: Iterable[float],
    *,
    raster_crs: Any,
    transform: Affine,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    values = [float(value) for value in bounds_wgs84]
    if len(values) != 4 or values[2] <= values[0] or values[3] <= values[1]:
        raise ReviewValidationError("视口 bounds 必须是 [west,south,east,north]。", code="invalid_viewport")
    source = CRS.from_user_input(raster_crs)
    converter = None if source.to_epsg() == 4326 else Transformer.from_crs(4326, source, always_xy=True)
    points = [(values[0], values[1]), (values[0], values[3]), (values[2], values[1]), (values[2], values[3])]
    if converter:
        points = [converter.transform(x, y) for x, y in points]
    inverse = ~transform
    pixels = [inverse * point for point in points]
    x1 = max(0, math.floor(min(point[0] for point in pixels)))
    y1 = max(0, math.floor(min(point[1] for point in pixels)))
    x2 = min(width, math.ceil(max(point[0] for point in pixels)))
    y2 = min(height, math.ceil(max(point[1] for point in pixels)))
    if x2 <= x1 or y2 <= y1:
        raise ReviewValidationError("当前视口与 TIFF 不相交。", code="viewport_outside_tiff")
    return x1, y1, x2 - x1, y2 - y1


class ReviewInferenceService:
    def __init__(
        self,
        db_url: str | None = None,
        *,
        session_service: ReviewSessionService | None = None,
        adapter_factory: Callable[[dict[str, Any]], ReviewModelAdapter] | None = None,
        tile_size: int = 1024,
        batch_size: int = 4,
    ):
        self.db_url = db_url
        self.sessions = session_service or ReviewSessionService(db_url)
        self.adapter_factory = adapter_factory
        self.tile_size = max(128, int(tile_size))
        self.batch_size = max(1, int(batch_size))

    def create_attempt(
        self,
        session_id: str,
        *,
        revision: int,
        prompt_type: str,
        prompts: list[dict[str, Any]],
        scope: dict[str, Any],
        merge_mode: str = "append",
        threshold: float = 0.25,
        visual_exemplars: list[dict[str, Any]] | None = None,
        parent_attempt_id: str | None = None,
    ) -> dict[str, Any]:
        if prompt_type not in {"text", "visual"}:
            raise ReviewValidationError("prompt_type 必须是 text 或 visual。", code="invalid_prompt_type")
        if merge_mode not in {"append", "replace_ai_in_scope"}:
            raise ReviewValidationError("不支持的候选合并模式。", code="invalid_merge_mode")
        scope_type = scope.get("type")
        if scope_type not in {"viewport", "full"}:
            raise ReviewValidationError("scope.type 必须是 viewport 或 full。", code="invalid_scope")
        if scope_type == "viewport" and not scope.get("bounds"):
            raise ReviewValidationError("视口 attempt 必须提供 WGS84 bounds。", code="viewport_required")
        if prompt_type == "text" and not prompts:
            raise ReviewValidationError("文本 attempt 至少需要一个 Prompt。", code="text_prompt_required")
        if prompt_type == "visual" and not visual_exemplars:
            raise ReviewValidationError("视觉 attempt 至少需要一个参考框。", code="visual_prompt_required")
        attempt = {
            "attempt_id": f"attempt_{uuid.uuid4().hex[:14]}",
            "status": "queued",
            "prompt_type": prompt_type,
            "prompts": prompts,
            "visual_exemplars": visual_exemplars or [],
            "scope": scope,
            "merge_mode": merge_mode,
            "threshold": max(0.0, min(1.0, float(threshold))),
            "progress": 0,
            "completed_windows": 0,
            "total_windows": 0,
            "candidate_count": 0,
            "candidates": [],
            "parent_attempt_id": parent_attempt_id,
            "created_at": _now(),
            "updated_at": _now(),
            "error": None,
        }
        self.sessions.apply_operations(
            session_id,
            revision,
            f"create-{attempt['attempt_id']}",
            [{"type": "upsert_attempt", "attempt": attempt}],
        )
        return attempt

    def get_attempt(self, session_id: str, attempt_id: str) -> dict[str, Any]:
        attempt = next((item for item in self.sessions.workspace(session_id).attempts if item.get("attempt_id") == attempt_id), None)
        if attempt is None:
            raise ReviewNotFound("attempt 不存在。", code="attempt_not_found", details={"attempt_id": attempt_id})
        return dict(attempt)

    def cancel_attempt(self, session_id: str, attempt_id: str) -> dict[str, Any]:
        attempt = self.get_attempt(session_id, attempt_id)
        if attempt["status"] in {"succeeded", "failed", "canceled", "applied"}:
            return attempt
        return self._update_attempt(session_id, {**attempt, "status": "canceled", "updated_at": _now()})

    def expand_attempt(self, session_id: str, attempt_id: str, *, revision: int) -> dict[str, Any]:
        source = self.get_attempt(session_id, attempt_id)
        return self.create_attempt(
            session_id,
            revision=revision,
            prompt_type=source["prompt_type"],
            prompts=source.get("prompts") or [],
            visual_exemplars=source.get("visual_exemplars") or [],
            scope={"type": "full"},
            merge_mode=source.get("merge_mode") or "append",
            threshold=float(source.get("threshold") or 0.25),
            parent_attempt_id=attempt_id,
        )

    def run_attempt(self, session_id: str, attempt_id: str, *, adapter: ReviewModelAdapter | None = None) -> dict[str, Any]:
        attempt = self.get_attempt(session_id, attempt_id)
        if attempt["status"] == "canceled":
            return attempt
        session = self.sessions.get(session_id)
        image_path, raster_meta = self._tiff_source(session.phase_id, session.tiff_id)
        adapter = adapter or self._adapter(attempt)
        attempt = self._update_attempt(session_id, {**attempt, "status": "running", "updated_at": _now()})
        try:
            import rasterio
            from rasterio.windows import Window

            with rasterio.open(image_path) as source:
                scope_window = self._scope_window(attempt["scope"], source)
                windows = list(_iter_windows(scope_window, self.tile_size))
                attempt = self._update_attempt(session_id, {**attempt, "total_windows": len(windows), "updated_at": _now()})
                context = self._prompt_context(adapter, attempt, source)
                candidates: list[dict[str, Any]] = []
                batch_size = self.batch_size
                index = 0
                retried_oom = False
                while index < len(windows):
                    current = self.get_attempt(session_id, attempt_id)
                    if current["status"] == "canceled":
                        return current
                    batch_specs = windows[index:index + batch_size]
                    batch = [
                        RasterWindow(x=x, y=y, width=w, height=h, pixels=source.read(window=Window(x, y, w, h)).transpose(1, 2, 0))
                        for x, y, w, h in batch_specs
                    ]
                    try:
                        predictions = adapter.predict_batch(batch, context)
                    except RuntimeError as exc:
                        if "out of memory" in str(exc).lower() and not retried_oom and batch_size > 1:
                            batch_size = max(1, batch_size // 2)
                            retried_oom = True
                            continue
                        raise
                    for prediction in predictions:
                        if prediction.score < float(attempt["threshold"]):
                            continue
                        mask_fields: dict[str, Any] = {}
                        if prediction.mask is not None and prediction.source_window:
                            mask_fields = mask_item_fields(prediction.mask, prediction.source_window, source.transform)
                        candidates.append({
                            "id": f"ai_{uuid.uuid4().hex[:12]}",
                            "species": prediction.category_id,
                            "confidence": prediction.score,
                            "box_px": mask_fields.get("box_px", prediction.box_px),
                            "source": "ai",
                            "confirmed": False,
                            "status": "pending",
                            "conflict": False,
                            "source_window": list(prediction.source_window or ()),
                            **mask_fields,
                        })
                    index += len(batch_specs)
                    attempt = self._update_attempt(session_id, {
                        **attempt,
                        "completed_windows": index,
                        "progress": round(index / max(1, len(windows)) * 100),
                        "candidate_count": len(candidates),
                        "updated_at": _now(),
                    })
            candidates = weighted_box_fusion(candidates, 0.6)
            return self._update_attempt(session_id, {
                **attempt,
                "status": "succeeded",
                "progress": 100,
                "candidate_count": len(candidates),
                "candidates": candidates,
                "oom_batch_reduced": retried_oom,
                "updated_at": _now(),
            })
        except Exception as exc:
            self._update_attempt(session_id, {**attempt, "status": "failed", "error": str(exc), "updated_at": _now()})
            raise

    def apply_attempt(self, session_id: str, attempt_id: str, *, revision: int, merge_mode: str | None = None) -> dict[str, Any]:
        attempt = self.get_attempt(session_id, attempt_id)
        if attempt["status"] != "succeeded":
            raise ReviewConflict("只有成功的 attempt 才能应用。", code="attempt_not_succeeded")
        workspace = self.sessions.workspace(session_id)
        mode = merge_mode or attempt.get("merge_mode") or "append"
        scope = None
        if attempt.get("scope", {}).get("type") == "viewport":
            _, meta = self._tiff_source(self.sessions.get(session_id).phase_id, self.sessions.get(session_id).tiff_id)
            scope = viewport_to_pixel_window(
                attempt["scope"]["bounds"], raster_crs=meta["crs"], transform=meta["transform"], width=meta["width"], height=meta["height"]
            )
            scope = (scope[0], scope[1], scope[0] + scope[2], scope[1] + scope[3])
        merged = ReviewMergeService().apply(mode, workspace.items, attempt.get("candidates") or [], scope)
        patch = self.sessions.apply_operations(
            session_id,
            revision,
            f"apply-{attempt_id}-{uuid.uuid4().hex[:6]}",
            [{"type": "apply_attempt", "attempt_id": attempt_id, "items": merged}],
        )
        return {"attempt_id": attempt_id, "status": "applied", "revision": patch.revision, "items": list(patch.items), "summary": patch.summary}

    def _update_attempt(self, session_id: str, attempt: dict[str, Any]) -> dict[str, Any]:
        for _ in range(3):
            session = self.sessions.get(session_id)
            try:
                self.sessions.apply_operations(
                    session_id,
                    session.revision,
                    f"attempt-{attempt['attempt_id']}-{uuid.uuid4().hex[:8]}",
                    [{"type": "upsert_attempt", "attempt": attempt}],
                )
                return attempt
            except ReviewConflict:
                continue
        raise ReviewConflict("attempt 状态与人工编辑持续冲突。", code="attempt_revision_conflict")

    def _tiff_source(self, phase_id: str, tiff_id: str) -> tuple[Path, dict[str, Any]]:
        init_db(self.db_url)
        conn = sqlite3.connect(resolve_db_path(self.db_url))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT path_versions, file_name, crs_epsg, crs_wkt, geotransform, pixel_width, pixel_height "
                "FROM tiffs WHERE phase_id=? AND tiff_id=?",
                (phase_id, tiff_id),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise ReviewNotFound("TIFF 不存在。", code="tiff_not_found")
        versions = json.loads(row["path_versions"] or "{}")
        paths = [Path(str(value)).expanduser() for _, value in sorted(versions.items(), reverse=True)]
        if row["file_name"]:
            paths.append(Path(row["file_name"]).expanduser())
        image = next((path.resolve() for path in paths if path.is_file()), None)
        if image is None:
            raise ReviewNotFound("TIFF 文件不可访问。", code="tiff_file_missing", details={"paths": [str(path) for path in paths]})
        transform = Affine(*json.loads(row["geotransform"])) if row["geotransform"] else None
        crs = CRS.from_epsg(int(row["crs_epsg"])) if row["crs_epsg"] else (CRS.from_wkt(row["crs_wkt"]) if row["crs_wkt"] else None)
        return image, {"transform": transform, "crs": crs, "width": row["pixel_width"], "height": row["pixel_height"]}

    @staticmethod
    def _scope_window(scope: dict[str, Any], source) -> tuple[int, int, int, int]:
        if scope.get("type") == "full":
            return 0, 0, source.width, source.height
        return viewport_to_pixel_window(
            scope["bounds"], raster_crs=source.crs, transform=source.transform, width=source.width, height=source.height
        )

    @staticmethod
    def _prompt_context(adapter: ReviewModelAdapter, attempt: dict[str, Any], source):
        if attempt["prompt_type"] == "text":
            return adapter.prepare_text_prompts(attempt["prompts"])
        exemplars = attempt.get("visual_exemplars") or []
        boxes = [list(map(float, item["box_px"])) for item in exemplars]
        categories = list(dict.fromkeys(str(item["category_id"]) for item in exemplars))
        category_index = {value: index for index, value in enumerate(categories)}
        classes = [category_index[str(item["category_id"])] for item in exemplars]
        from rasterio.enums import Resampling
        from rasterio.windows import Window

        left = max(0, math.floor(min(box[0] for box in boxes)) - 32)
        top = max(0, math.floor(min(box[1] for box in boxes)) - 32)
        right = min(source.width, math.ceil(max(box[2] for box in boxes)) + 32)
        bottom = min(source.height, math.ceil(max(box[3] for box in boxes)) + 32)
        width, height = right - left, bottom - top
        scale = min(1.0, 4096 / max(width, height))
        out_width, out_height = max(1, round(width * scale)), max(1, round(height * scale))
        reference = source.read(
            window=Window(left, top, width, height),
            out_shape=(source.count, out_height, out_width),
            resampling=Resampling.bilinear,
        ).transpose(1, 2, 0)
        local_boxes = [[
            (box[0] - left) * scale,
            (box[1] - top) * scale,
            (box[2] - left) * scale,
            (box[3] - top) * scale,
        ] for box in boxes]
        return adapter.prepare_visual_prompts(reference, local_boxes, classes, categories)

    def _adapter(self, attempt: dict[str, Any]) -> ReviewModelAdapter:
        if self.adapter_factory:
            return self.adapter_factory(attempt)
        return MockReviewAdapter()


def build_review_adapter(settings) -> ReviewModelAdapter:
    name = str(settings.get("review.adapter", "yoloe"))
    if name == "mock_review":
        return MockReviewAdapter()
    variant = str(settings.get("review.model_variant", "26x"))
    return YOLOEReviewAdapter(
        settings.get(f"review.models.{variant}.weights"),
        mobileclip=settings.get("review.mobileclip_weights"),
        device=settings.get("review.device", settings.get("detect.device")),
        conf=float(settings.get("review.conf_threshold", 0.25)),
        imgsz=int(settings.get("review.model_input", 1024)),
    )


def _iter_windows(scope: tuple[int, int, int, int], tile_size: int):
    left, top, width, height = scope
    for y in range(top, top + height, tile_size):
        for x in range(left, left + width, tile_size):
            yield x, y, min(tile_size, left + width - x), min(tile_size, top + height - y)
