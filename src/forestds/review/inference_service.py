"""交互式复核 attempt：范围换算、分块推理、进度、取消与候选合并。"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from affine import Affine
from pyproj import CRS, Transformer

from ..db.schema import init_db, resolve_db_path
from ..effective_area.windows import load_effective_window_filter
from .domain import ReviewConflict, ReviewNotFound, ReviewValidationError
from .merge_service import ReviewMergeService, weighted_box_fusion
from .models import MockReviewAdapter, RasterWindow, ReviewModelAdapter
from .models.yoloe import YOLOEReviewAdapter
from .masks import mask_item_fields
from .session_service import ReviewSessionService


log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _normalize_scope(scope: Any) -> dict[str, Any]:
    """校验并归一化 attempt 的识别范围。

    - ``{"type": "full"}``: 全图识别;
    - ``{"type": "region", "center_px": [cx, cy], "side_px": n}``: 以图像像素为准的正方形范围。
    """
    if not isinstance(scope, dict):
        raise ReviewValidationError("scope 必须是对象。", code="invalid_scope")
    scope_type = scope.get("type")
    if scope_type not in {"region", "full"}:
        raise ReviewValidationError("scope.type 必须是 region 或 full。", code="invalid_scope")
    if scope_type == "full":
        return {"type": "full"}

    center = scope.get("center_px")
    if not isinstance(center, (list, tuple)) or len(center) != 2:
        raise ReviewValidationError(
            "region 范围必须提供 center_px=[cx, cy]。", code="region_center_required"
        )
    try:
        center_x, center_y = (float(value) for value in center)
        side = float(scope.get("side_px"))
    except (TypeError, ValueError) as exc:
        raise ReviewValidationError(
            "region 范围的 center_px / side_px 必须是数字。", code="invalid_scope"
        ) from exc
    if not math.isfinite(center_x) or not math.isfinite(center_y):
        raise ReviewValidationError("region 中心点无效。", code="invalid_scope")
    if not math.isfinite(side) or side <= 0:
        raise ReviewValidationError("region 边长必须大于零。", code="invalid_scope")
    return {"type": "region", "center_px": [center_x, center_y], "side_px": side}


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


def _ensure_rgb(img: Any) -> Any:
    """确保输入图像像素数组恒为连续的 (H, W, 3) 标准三通道 RGB uint8 数组。
    安全兼容 (C, H, W)、(H, W, C)、(H, W)、uint16、float32、单通道、4 通道 (RGBA/NIR) 等任意形态。
    """
    import numpy as np
    if not isinstance(img, np.ndarray):
        img = np.asarray(img)
    if img.ndim == 4:
        img = img[0]
    if img.ndim == 2:
        img = np.repeat(img[:, :, None], 3, axis=2)
    elif img.ndim == 3:
        # 若为 (C, H, W) 格式，先转为 (H, W, C)
        if img.shape[0] in (1, 2, 3, 4, 5, 8) and img.shape[0] < min(img.shape[1], img.shape[2]):
            img = img.transpose(1, 2, 0)
        if img.shape[2] == 1:
            img = np.repeat(img, 3, axis=2)
        elif img.shape[2] >= 4:
            img = img[:, :, :3]
        elif img.shape[2] == 2:
            img = np.pad(img, ((0, 0), (0, 0), (0, 1)), mode="edge")

    # 规范化像素值到 uint8 (0~255)
    if img.dtype != np.uint8:
        if np.issubdtype(img.dtype, np.floating):
            max_val = float(np.nanmax(img)) if img.size else 1.0
            if max_val <= 1.0:
                img = (np.clip(img, 0, 1) * 255.0).astype(np.uint8)
            else:
                img = np.clip(img, 0, 255).astype(np.uint8)
        elif img.dtype in (np.uint16, np.int16, np.uint32, np.int32):
            max_val = float(np.max(img)) if img.size else 255.0
            if max_val > 255.0:
                img = np.clip(img / (max_val / 255.0), 0, 255).astype(np.uint8)
            else:
                img = np.clip(img, 0, 255).astype(np.uint8)
        else:
            img = np.clip(img, 0, 255).astype(np.uint8)

    return np.ascontiguousarray(img)


class ReviewInferenceService:
    def __init__(
        self,
        db_url: str | None = None,
        *,
        session_service: ReviewSessionService | None = None,
        adapter_factory: Callable[[dict[str, Any]], ReviewModelAdapter] | None = None,
        tile_size: int = 1024,
        batch_size: int = 4,
        viewport_max_windows: int = 256,
        max_candidates: int = 50_000,
        effective_area_cache_size: int = 32,
    ):
        self.db_url = db_url
        self.sessions = session_service or ReviewSessionService(db_url)
        self.adapter_factory = adapter_factory
        self.tile_size = max(128, int(tile_size))
        self.batch_size = max(1, int(batch_size))
        self.viewport_max_windows = max(1, int(viewport_max_windows))
        self.max_candidates = max(1, int(max_candidates))
        self.effective_area_cache_size = max(1, int(effective_area_cache_size))

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
        if merge_mode not in {"append", "replace_all"}:
            raise ReviewValidationError("不支持的候选合并模式。", code="invalid_merge_mode")
        scope = _normalize_scope(scope)
        scope_type = scope["type"]
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
        # 使用当前最新草稿 revision，避免上一次尝试失败递增 revision 后导致 409 冲突
        workspace = self.sessions.drafts.load(session_id)
        effective_revision = workspace.revision if workspace is not None else revision
        self.sessions.apply_operations(
            session_id,
            effective_revision,
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
        started_at = time.perf_counter()
        try:
            import numpy as np
            import rasterio
            from rasterio.windows import Window

            with rasterio.open(image_path) as source:
                scope_window = self._scope_window(attempt["scope"], source)
                window_filter = self._window_filter(session, image_path, raster_meta)
                planned = list(_iter_windows(scope_window, self.tile_size))
                # 有效区域之外的切片不必读盘、不必推理，直接从任务量中剔除。
                windows = (
                    [spec for spec in planned if window_filter.classify(spec) != "outside"]
                    if window_filter is not None
                    else planned
                )
                skipped_windows = len(planned) - len(windows)
                if attempt["scope"]["type"] == "region" and len(windows) > self.viewport_max_windows:
                    raise ReviewValidationError(
                        "当前识别范围需要处理的切片过多，请缩小范围后重试。",
                        code="region_window_limit",
                        details={"windows": len(windows), "limit": self.viewport_max_windows},
                    )
                log.info(
                    "复核 attempt %s 切片规划：范围=%s 像素窗口=%dx%d 切片=%d 有效=%d 区外跳过=%d 切片尺寸=%d",
                    attempt_id,
                    attempt["scope"]["type"],
                    scope_window[2],
                    scope_window[3],
                    len(planned),
                    len(windows),
                    skipped_windows,
                    self.tile_size,
                )
                attempt = self._update_attempt(session_id, {
                    **attempt,
                    "total_windows": len(windows),
                    "skipped_windows": skipped_windows,
                    "updated_at": _now(),
                })
                context = self._prompt_context(adapter, attempt, source)
                candidates: list[dict[str, Any]] = []
                batch_size = self.batch_size
                index = 0
                retried_oom = False
                candidates_truncated = False
                dropped_outside = 0
                while index < len(windows):
                    current = self.get_attempt(session_id, attempt_id)
                    if current["status"] == "canceled":
                        return current
                    batch_specs = windows[index:index + batch_size]
                    batch = []
                    for x, y, w, h in batch_specs:
                        raw_pixels = source.read(window=Window(x, y, w, h)).transpose(1, 2, 0)
                        pixels = _ensure_rgb(raw_pixels)
                        if window_filter is not None:
                            local_mask = window_filter.local_mask((x, y, w, h))
                            if local_mask is not None:
                                # 边界切片：区外像素置零，避免模型在无效区域产生检测。
                                pixels = np.where(local_mask[..., None], pixels, 0)
                        batch.append(RasterWindow(x=x, y=y, width=w, height=h, pixels=pixels))
                    try:
                        predictions = adapter.predict_batch(batch, context)
                    except RuntimeError as exc:
                        if "out of memory" in str(exc).lower() and not retried_oom and batch_size > 1:
                            batch_size = max(1, batch_size // 2)
                            retried_oom = True
                            log.warning("复核 attempt %s 显存不足，batch_size 降为 %d 重试", attempt_id, batch_size)
                            continue
                        raise
                    for prediction in predictions:
                        if prediction.score < float(attempt["threshold"]):
                            continue
                        mask_fields: dict[str, Any] = {}
                        if prediction.mask is not None and prediction.source_window:
                            mask_fields = mask_item_fields(prediction.mask, prediction.source_window, source.transform)
                        box_px = mask_fields.get("box_px", prediction.box_px)
                        if window_filter is not None and not _keep_box(window_filter, box_px):
                            dropped_outside += 1
                            continue
                        candidates.append({
                            "id": f"ai_{uuid.uuid4().hex[:12]}",
                            "species": prediction.category_id,
                            "confidence": prediction.score,
                            "box_px": box_px,
                            "source": "ai",
                            "confirmed": False,
                            "status": "pending",
                            "conflict": False,
                            "frozen": False,
                            "source_window": list(prediction.source_window or ()),
                            **mask_fields,
                        })
                        if len(candidates) >= self.max_candidates:
                            candidates_truncated = True
                            break
                    index += len(batch_specs)
                    attempt = self._update_attempt(session_id, {
                        **attempt,
                        "completed_windows": index,
                        "progress": round(index / max(1, len(windows)) * 100),
                        "candidate_count": len(candidates),
                        "updated_at": _now(),
                    })
                    if candidates_truncated:
                        break
            raw_count = len(candidates)
            candidates = weighted_box_fusion(candidates, 0.6)
            elapsed = time.perf_counter() - started_at
            log.info(
                "复核 attempt %s 完成：切片=%d 原始候选=%d 融合后=%d 区外丢弃=%d 耗时=%.1fs",
                attempt_id, len(windows), raw_count, len(candidates), dropped_outside, elapsed,
            )
            return self._update_attempt(session_id, {
                **attempt,
                "status": "succeeded",
                "progress": 100,
                "candidate_count": len(candidates),
                "candidates": candidates,
                "oom_batch_reduced": retried_oom,
                "candidates_truncated": candidates_truncated,
                "dropped_outside": dropped_outside,
                "elapsed_seconds": round(elapsed, 3),
                "updated_at": _now(),
            })
        except Exception as exc:
            log.exception("复核 attempt %s 执行失败", attempt_id)
            self._update_attempt(session_id, {**attempt, "status": "failed", "error": str(exc), "updated_at": _now()})
            raise

    def apply_attempt(self, session_id: str, attempt_id: str, *, revision: int, merge_mode: str | None = None) -> dict[str, Any]:
        attempt = self.get_attempt(session_id, attempt_id)
        if attempt["status"] != "succeeded":
            raise ReviewConflict("只有成功的 attempt 才能应用。", code="attempt_not_succeeded")
        workspace = self.sessions.workspace(session_id)
        mode = merge_mode or attempt.get("merge_mode") or "append"
        if mode not in {"append", "replace_all"}:
            raise ReviewValidationError("不支持的候选合并模式。", code="invalid_merge_mode")
        merged = ReviewMergeService().apply(mode, workspace.items, attempt.get("candidates") or [])
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
                "SELECT t.path_versions, t.file_name, t.crs_epsg, t.crs_wkt, t.geotransform, "
                "t.pixel_width, t.pixel_height, tp.tract_pk "
                "FROM tiffs t "
                "LEFT JOIN tract_phases tp ON tp.tract_phase_pk = t.tract_phase_pk "
                "WHERE t.phase_id=? AND t.tiff_id=?",
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
        return image, {
            "transform": transform,
            "crs": crs,
            "width": row["pixel_width"],
            "height": row["pixel_height"],
            "tract_pk": row["tract_pk"],
        }

    def _window_filter(self, session, image_path: Path, raster_meta: dict[str, Any]):
        """构建有效区域像素过滤器; 无地理参考或未划定有效区域时返回 None。"""
        tract_ref = raster_meta.get("tract_pk")
        if not tract_ref:
            return None
        try:
            return load_effective_window_filter(
                db_url=self.db_url,
                tract_ref=str(tract_ref),
                phase_id=session.phase_id,
                tiff_id=session.tiff_id,
                image_path=str(image_path),
                raster_crs=raster_meta.get("crs"),
                geotransform=raster_meta.get("transform"),
                cache_size=self.effective_area_cache_size,
            )
        except Exception:
            # 有效区域过滤是质量增强而非正确性前提, 构建失败时降级为全范围推理。
            log.warning("复核有效区域过滤器构建失败，已降级为全范围推理", exc_info=True)
            return None

    @staticmethod
    def _scope_window(scope: dict[str, Any], source) -> tuple[int, int, int, int]:
        """将 scope 换算为全局像素窗口 (x, y, width, height)。"""
        if scope.get("type") == "full":
            return 0, 0, source.width, source.height
        center_x, center_y = (float(value) for value in scope["center_px"])
        half = float(scope["side_px"]) / 2
        x1 = max(0, int(math.floor(center_x - half)))
        y1 = max(0, int(math.floor(center_y - half)))
        x2 = min(int(source.width), int(math.ceil(center_x + half)))
        y2 = min(int(source.height), int(math.ceil(center_y + half)))
        if x2 <= x1 or y2 <= y1:
            raise ReviewValidationError(
                "识别范围与当前 TIFF 不相交。",
                code="region_outside_tiff",
                details={"center_px": scope["center_px"], "side_px": scope["side_px"]},
            )
        return x1, y1, x2 - x1, y2 - y1

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
        raw_reference = source.read(
            window=Window(left, top, width, height),
            out_shape=(source.count, out_height, out_width),
            resampling=Resampling.bilinear,
        ).transpose(1, 2, 0)
        reference = _ensure_rgb(raw_reference)
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


def _keep_box(window_filter, box_px: Any) -> bool:
    """按检测框中心点判定是否落在有效区域内。"""
    if not isinstance(box_px, (list, tuple)) or len(box_px) != 4:
        return True
    try:
        x1, y1, x2, y2 = (float(value) for value in box_px)
    except (TypeError, ValueError):
        return True
    return bool(window_filter.keep_detection(((x1 + x2) / 2, (y1 + y2) / 2)))


def _iter_windows(scope: tuple[int, int, int, int], tile_size: int):
    left, top, width, height = scope
    for y in range(top, top + height, tile_size):
        for x in range(left, left + width, tile_size):
            yield x, y, min(tile_size, left + width - x), min(tile_size, top + height - y)
