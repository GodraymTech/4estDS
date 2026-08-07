"""可恢复单 TIFF 复核会话服务。"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..db.schema import init_db, resolve_db_path
from .domain import (
    FROZEN_EDITABLE_FIELDS,
    ReviewConflict,
    ReviewMode,
    ReviewNotFound,
    ReviewSession,
    ReviewValidationError,
    ReviewWorkspace,
    WorkspacePatch,
    is_frozen,
    workspace_summary,
)
from .drafts import DraftStore


_MODE_LABELS = {"inherit": "继承", "fresh": "从 0 开始"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _connect(url: str | None) -> sqlite3.Connection:
    init_db(url)
    conn = sqlite3.connect(resolve_db_path(url), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _loads(raw: str | None, default):
    try:
        return json.loads(raw) if raw else default
    except (TypeError, json.JSONDecodeError):
        return default


def _session(row: sqlite3.Row) -> ReviewSession:
    return ReviewSession(**{key: row[key] for key in ReviewSession.__dataclass_fields__})


def _item_from_observation(row: sqlite3.Row) -> dict[str, Any]:
    box = _loads(row["box_px"], [0.0, 0.0, 0.0, 0.0])
    return {
        "id": row["observation_id"],
        "parent_observation_id": row["observation_id"],
        "individual_id": row["individual_id"],
        "species": row["species"] or "",
        "confidence": row["confidence"],
        "box_px": box,
        "box_geo": _loads(row["box_geo"], None),
        "center_geom": row["center_geom"],
        "crown_geom": row["crown_geom"],
        "source": "parent",
        "confirmed": True,
        "status": "accepted",
        "note": "",
        "conflict": False,
        "frozen": False,
    }


def _tiff_geo_reference(conn: sqlite3.Connection, phase_id: str, tiff_id: str):
    """加载 TIFF 像素到原始 CRS / WGS84 的转换器。

    返回 ``(Affine, to_wgs84)``；缺少地理参考时返回 ``None``。转换器仅在一次
    会话命令内构造一次，避免批量编辑时重复初始化 pyproj。
    """
    row = conn.execute(
        "SELECT geotransform, crs_epsg, crs_wkt FROM tiffs WHERE phase_id=? AND tiff_id=?",
        (phase_id, tiff_id),
    ).fetchone()
    if row is None or not row["geotransform"] or not (row["crs_epsg"] or row["crs_wkt"]):
        return None
    from affine import Affine
    from pyproj import CRS, Transformer

    transform = Affine(*json.loads(row["geotransform"]))
    crs = CRS.from_epsg(int(row["crs_epsg"])) if row["crs_epsg"] else CRS.from_wkt(row["crs_wkt"])
    to_wgs84 = None if crs.to_epsg() == 4326 else Transformer.from_crs(crs, 4326, always_xy=True)
    return transform, to_wgs84


def _with_geography(item: Mapping[str, Any], geo_reference) -> dict[str, Any]:
    """由事实源 ``box_px`` 派生原始 CRS 与 WGS84 框，供发布与地图渲染。"""
    value = dict(item)
    box = value.get("box_px")
    if geo_reference is None or not isinstance(box, list) or len(box) != 4:
        return value
    transform, to_wgs84 = geo_reference
    x1, y1, x2, y2 = (float(part) for part in box)
    native = [transform * (x, y) for x, y in ((x1, y1), (x1, y2), (x2, y1), (x2, y2))]
    wgs84 = [to_wgs84.transform(x, y) for x, y in native] if to_wgs84 else native
    native_x = [point[0] for point in native]
    native_y = [point[1] for point in native]
    lng = [point[0] for point in wgs84]
    lat = [point[1] for point in wgs84]
    value["box_geo"] = [min(native_x), min(native_y), max(native_x), max(native_y)]
    value["box_wgs84"] = [min(lng), min(lat), max(lng), max(lat)]
    center_native = transform * ((x1 + x2) / 2, (y1 + y2) / 2)
    value["center_geom"] = f"POINT({center_native[0]} {center_native[1]})"
    return value


_EDITABLE_METADATA = (
    "category_catalog",
    "visible_categories",
    "active_category",
    "text_prompts",
    "visual_exemplars",
    "attempts",
)


def _copy(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _editable_snapshot(workspace: ReviewWorkspace) -> dict[str, Any]:
    return {
        "items": _copy(workspace.items),
        "category_catalog": _copy(workspace.category_catalog),
        "visible_categories": list(workspace.visible_categories),
        "active_category": workspace.active_category,
        "text_prompts": _copy(workspace.text_prompts),
        "visual_exemplars": _copy(workspace.visual_exemplars),
        "attempts": _copy(workspace.attempts),
    }


def _history_scope(operations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    item_ids: set[str] = set()
    metadata: set[str] = set()
    for operation in operations:
        kind = str(operation.get("type") or "")
        if kind == "apply_attempt":
            return {"kind": "full"}
        if kind in {"add", "delete", "update", "set_category", "set_note", "set_status"}:
            item = operation.get("item") if kind == "add" else None
            item_id = (item or {}).get("id") if isinstance(item, Mapping) else operation.get("item_id")
            if item_id:
                item_ids.add(str(item_id))
        elif kind == "bulk_status":
            item_ids.update(str(value) for value in operation.get("item_ids") or [])
        elif kind == "set_catalog":
            metadata.update({"category_catalog", "visible_categories", "active_category"})
        elif kind != "upsert_attempt":
            return {"kind": "full"}
    return {"kind": "delta", "item_ids": sorted(item_ids), "metadata": sorted(metadata)}


def _scoped_snapshot(workspace: ReviewWorkspace, scope: Mapping[str, Any]) -> dict[str, Any]:
    if scope.get("kind") == "full":
        return _editable_snapshot(workspace)
    requested = {str(value) for value in scope.get("item_ids") or []}
    items: dict[str, Any] = {item_id: None for item_id in requested}
    for index, item in enumerate(workspace.items):
        item_id = str(item.get("id"))
        if item_id in requested:
            items[item_id] = {"index": index, "value": _copy(item)}
    metadata = {
        key: _copy(getattr(workspace, key))
        for key in scope.get("metadata") or []
        if key in _EDITABLE_METADATA
    }
    return {
        "_kind": "delta",
        "item_ids": sorted(requested),
        "items": items,
        "metadata": metadata,
    }


def _snapshot_for_entry(workspace: ReviewWorkspace, entry: Mapping[str, Any]) -> dict[str, Any]:
    if entry.get("_kind") != "delta":
        return _editable_snapshot(workspace)
    return _scoped_snapshot(
        workspace,
        {
            "kind": "delta",
            "item_ids": entry.get("item_ids") or [],
            "metadata": list((entry.get("metadata") or {}).keys()),
        },
    )


def _restore(workspace: ReviewWorkspace, snapshot: Mapping[str, Any]) -> None:
    if snapshot.get("_kind") == "delta":
        item_ids = {str(value) for value in snapshot.get("item_ids") or []}
        workspace.items = [item for item in workspace.items if str(item.get("id")) not in item_ids]
        previous = [value for value in (snapshot.get("items") or {}).values() if value is not None]
        for value in sorted(previous, key=lambda item: int(item["index"])):
            index = min(max(0, int(value["index"])), len(workspace.items))
            workspace.items.insert(index, _copy(value["value"]))
        for key, value in (snapshot.get("metadata") or {}).items():
            if key in _EDITABLE_METADATA:
                setattr(workspace, key, _copy(value))
        return
    for key in ("items", *_EDITABLE_METADATA):
        if key in snapshot:
            setattr(workspace, key, _copy(snapshot[key]))


class ReviewSessionService:
    def __init__(self, db_url: str | None = None, *, draft_root: Path | None = None):
        self.db_url = db_url
        self.drafts = DraftStore(draft_root)

    def create(
        self,
        phase_id: str,
        tiff_id: str,
        mode: ReviewMode,
        base_run_id: str | None = None,
    ) -> ReviewSession:
        if mode not in {"inherit", "fresh"}:
            raise ReviewValidationError("不支持的复核初始化模式。", code="invalid_review_mode")
        conn = _connect(self.db_url)
        path: Path | None = None
        try:
            tiff = conn.execute(
                "SELECT tiff_id, phase_id, tract_phase_pk, active_run_id FROM tiffs WHERE phase_id=? AND tiff_id=?",
                (phase_id, tiff_id),
            ).fetchone()
            if tiff is None:
                raise ReviewNotFound("TIFF 不存在。", code="tiff_not_found", details={"phase_id": phase_id, "tiff_id": tiff_id})

            # 同一 TIFF 同时只允许一个进行中的复核会话:
            # 同模式幂等返回已有会话, 异模式直接拒绝, 避免两份草稿互相覆盖发布。
            active = conn.execute(
                "SELECT * FROM review_sessions WHERE phase_id=? AND tiff_id=? AND status='active' "
                "ORDER BY created_at DESC LIMIT 1",
                (phase_id, tiff_id),
            ).fetchone()
            if active is not None:
                if active["mode"] == mode:
                    return _session(active)
                raise ReviewConflict(
                    f"该 TIFF 已有进行中的{_MODE_LABELS.get(active['mode'], active['mode'])}模式复核，"
                    "请先完成或删除后再创建新模式会话。",
                    code="review_session_exists",
                    details={
                        "session_id": active["session_id"],
                        "mode": active["mode"],
                        "phase_id": phase_id,
                        "tiff_id": tiff_id,
                    },
                )

            expected_active = tiff["active_run_id"]
            resolved_base = base_run_id
            if mode == "inherit":
                resolved_base = base_run_id or expected_active
                if not resolved_base:
                    raise ReviewValidationError("当前 TIFF 尚无已发布结果，请选择从 0 开始。", code="active_run_required")
                base = conn.execute(
                    "SELECT run_id FROM runs WHERE run_id=? AND phase_id=? AND tiff_id=? AND status='succeeded'",
                    (resolved_base, phase_id, tiff_id),
                ).fetchone()
                if base is None:
                    raise ReviewValidationError("基线 run 与当前 TIFF 不匹配或尚未成功。", code="invalid_base_run")
            elif base_run_id is not None:
                raise ReviewValidationError("从 0 开始不能指定 base_run_id。", code="unexpected_base_run")

            rows = []
            if resolved_base:
                rows = conn.execute(
                    "SELECT * FROM tree_observations WHERE run_id=? AND phase_id=? AND tiff_id=? ORDER BY observation_id",
                    (resolved_base, phase_id, tiff_id),
                ).fetchall()
            geo_reference = _tiff_geo_reference(conn, phase_id, tiff_id)
            items = [_with_geography(_item_from_observation(row), geo_reference) for row in rows]
            species = sorted({item["species"] for item in items if item["species"]})
            catalog = [
                {"id": name, "display_name": name, "model_prompt": name, "color": _category_color(index)}
                for index, name in enumerate(species)
            ]
            workspace = ReviewWorkspace(
                items=items,
                category_catalog=catalog,
                visible_categories=species,
                active_category=species[0] if species else None,
                visual_exemplars=[],
            )
            session_id = f"review_{uuid.uuid4().hex[:16]}"
            path = self.drafts.save(session_id, workspace)
            now = _now()
            conn.execute(
                "INSERT INTO review_sessions "
                "(session_id, phase_id, tiff_id, tract_phase_pk, mode, base_run_id, expected_active_run_id, "
                "status, revision, draft_path, summary_json, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    session_id, phase_id, tiff_id, tiff["tract_phase_pk"], mode, resolved_base,
                    expected_active, "active", 0, str(path),
                    json.dumps(workspace_summary(items), ensure_ascii=False), now, now,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM review_sessions WHERE session_id=?", (session_id,)).fetchone()
            return _session(row)
        except Exception:
            conn.rollback()
            if path is not None and path.exists():
                path.unlink()
            raise
        finally:
            conn.close()

    def get(self, session_id: str) -> ReviewSession:
        conn = _connect(self.db_url)
        try:
            row = conn.execute("SELECT * FROM review_sessions WHERE session_id=?", (session_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise ReviewNotFound("复核会话不存在。", code="session_not_found", details={"session_id": session_id})
        return _session(row)

    def list(self, *, status: str | None = None) -> list[ReviewSession]:
        conn = _connect(self.db_url)
        try:
            if status:
                rows = conn.execute(
                    "SELECT * FROM review_sessions WHERE status=? ORDER BY updated_at DESC", (status,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM review_sessions ORDER BY updated_at DESC").fetchall()
            return [_session(row) for row in rows]
        finally:
            conn.close()

    def workspace(self, session_id: str) -> ReviewWorkspace:
        session = self.get(session_id)
        workspace = self.drafts.load(session_id)
        missing = [item for item in workspace.items if item.get("box_px") and not item.get("box_wgs84")]
        if missing:
            conn = _connect(self.db_url)
            try:
                geo_reference = _tiff_geo_reference(conn, session.phase_id, session.tiff_id)
            finally:
                conn.close()
            workspace.items = [_with_geography(item, geo_reference) for item in workspace.items]
        return workspace

    def _assert_writable(self, session: ReviewSession) -> None:
        if session.status != "active":
            raise ReviewConflict("复核会话已结束，不能继续修改。", code="session_not_active")

    def _persist(
        self,
        session: ReviewSession,
        workspace: ReviewWorkspace,
        operation_id: str,
        *,
        changed_item_ids: Sequence[str] = (),
        deleted_item_ids: Sequence[str] = (),
        replace_all: bool = False,
    ) -> WorkspacePatch:
        workspace.revision += 1
        workspace.applied_operations[operation_id] = workspace.revision
        if len(workspace.applied_operations) > 2000:
            workspace.applied_operations = dict(list(workspace.applied_operations.items())[-1000:])
        self.drafts.save(session.session_id, workspace)
        summary = workspace_summary(workspace.items)
        conn = _connect(self.db_url)
        try:
            updated = conn.execute(
                "UPDATE review_sessions SET revision=?, summary_json=?, updated_at=? "
                "WHERE session_id=? AND revision=? AND status='active'",
                (
                    workspace.revision,
                    json.dumps(summary, ensure_ascii=False),
                    _now(),
                    session.session_id,
                    session.revision,
                ),
            )
            if updated.rowcount != 1:
                raise ReviewConflict("复核草稿已被其他窗口更新，请重新加载。", code="revision_conflict")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        changed = {str(value) for value in changed_item_ids}
        changed_items = tuple(item for item in workspace.items if str(item.get("id")) in changed)
        return WorkspacePatch(
            session.session_id,
            workspace.revision,
            tuple(workspace.items),
            summary,
            changed_items,
            tuple(str(value) for value in deleted_item_ids),
            replace_all,
        )

    def _existing_patch(self, session_id: str, workspace: ReviewWorkspace) -> WorkspacePatch:
        return WorkspacePatch(session_id, workspace.revision, tuple(workspace.items), workspace_summary(workspace.items))

    def apply_operations(
        self,
        session_id: str,
        revision: int,
        operation_id: str,
        operations: Sequence[Mapping[str, Any]],
    ) -> WorkspacePatch:
        if not operation_id:
            raise ReviewValidationError("operation_id 不能为空。", code="operation_id_required")
        session = self.get(session_id)
        self._assert_writable(session)
        workspace = self.drafts.load(session_id)
        if operation_id in workspace.applied_operations:
            return self._existing_patch(session_id, workspace)
        if revision != session.revision or revision != workspace.revision:
            raise ReviewConflict(
                "复核草稿版本冲突，请重新加载。",
                code="revision_conflict",
                details={"expected": workspace.revision, "received": revision},
            )
        if not operations:
            raise ReviewValidationError("operations 不能为空。", code="operations_required")
        normalized = [dict(operation) for operation in operations]
        for operation in normalized:
            if str(operation.get("type") or "") == "add":
                item = dict(operation.get("item") or {})
                item.setdefault("id", f"item_{uuid.uuid4().hex[:12]}")
                operation["item"] = item
        record_history = any(str(operation.get("type") or "") not in {"upsert_attempt"} for operation in normalized)
        scope = _history_scope(normalized)
        if record_history:
            workspace.undo_stack.append(_scoped_snapshot(workspace, scope))
            workspace.undo_stack = workspace.undo_stack[-100:]
            workspace.redo_stack.clear()
        for operation in normalized:
            self._apply(workspace, operation)
        # AI 候选与人工新增/缩放都只提交 box_px；在服务端集中派生地理坐标，
        # 避免浏览器自行实现 CRS 投影并确保发布数据与地图显示一致。
        needs_geography = any(
            str(operation.get("type") or "") in {"add", "apply_attempt"}
            or (
                str(operation.get("type") or "") == "update"
                and "box_px" in dict(operation.get("patch") or {})
            )
            for operation in normalized
        ) or any(item.get("box_px") and not item.get("box_wgs84") for item in workspace.items)
        if needs_geography:
            conn = _connect(self.db_url)
            try:
                geo_reference = _tiff_geo_reference(conn, session.phase_id, session.tiff_id)
            finally:
                conn.close()
            workspace.items = [_with_geography(item, geo_reference) for item in workspace.items]
        item_ids = {str(value) for value in scope.get("item_ids") or []}
        current_ids = {str(item.get("id")) for item in workspace.items}
        return self._persist(
            session,
            workspace,
            operation_id,
            changed_item_ids=sorted(item_ids & current_ids),
            deleted_item_ids=sorted(item_ids - current_ids),
            replace_all=scope.get("kind") == "full",
        )

    def undo(self, session_id: str, revision: int, operation_id: str) -> WorkspacePatch:
        session = self.get(session_id)
        self._assert_writable(session)
        workspace = self.drafts.load(session_id)
        if operation_id in workspace.applied_operations:
            return self._existing_patch(session_id, workspace)
        self._check_revision(session, workspace, revision)
        if not workspace.undo_stack:
            raise ReviewValidationError("没有可撤销的操作。", code="nothing_to_undo")
        target = workspace.undo_stack.pop()
        workspace.redo_stack.append(_snapshot_for_entry(workspace, target))
        _restore(workspace, target)
        return self._persist(session, workspace, operation_id, replace_all=True)

    def redo(self, session_id: str, revision: int, operation_id: str) -> WorkspacePatch:
        session = self.get(session_id)
        self._assert_writable(session)
        workspace = self.drafts.load(session_id)
        if operation_id in workspace.applied_operations:
            return self._existing_patch(session_id, workspace)
        self._check_revision(session, workspace, revision)
        if not workspace.redo_stack:
            raise ReviewValidationError("没有可重做的操作。", code="nothing_to_redo")
        target = workspace.redo_stack.pop()
        workspace.undo_stack.append(_snapshot_for_entry(workspace, target))
        _restore(workspace, target)
        return self._persist(session, workspace, operation_id, replace_all=True)

    @staticmethod
    def _check_revision(session: ReviewSession, workspace: ReviewWorkspace, revision: int) -> None:
        if revision != session.revision or revision != workspace.revision:
            raise ReviewConflict("复核草稿版本冲突，请重新加载。", code="revision_conflict")

    def cancel(self, session_id: str, revision: int) -> ReviewSession:
        session = self.get(session_id)
        self._assert_writable(session)
        workspace = self.drafts.load(session_id)
        self._check_revision(session, workspace, revision)
        conn = _connect(self.db_url)
        try:
            conn.execute(
                "UPDATE review_sessions SET status='canceled', updated_at=? WHERE session_id=? AND status='active'",
                (_now(), session_id),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get(session_id)

    def delete(self, session_id: str) -> None:
        session = self.get(session_id)
        if session.status == "published":
            raise ReviewConflict("已发布的复核会话无法删除。", code="cannot_delete_published_session")
        conn = _connect(self.db_url)
        try:
            conn.execute("DELETE FROM review_sessions WHERE session_id=?", (session_id,))
            conn.commit()
        finally:
            conn.close()
        self.drafts.delete(session_id)

    def apply_mask_operation(
        self,
        session_id: str,
        revision: int,
        operation_id: str,
        item_id: str,
        strokes: Sequence[Mapping[str, Any]],
    ) -> WorkspacePatch:
        if not strokes:
            raise ReviewValidationError("mask 画笔不能为空。", code="mask_strokes_required")
        session = self.get(session_id)
        self._assert_writable(session)
        workspace = self.drafts.load(session_id)
        if operation_id in workspace.applied_operations:
            return self._existing_patch(session_id, workspace)
        self._check_revision(session, workspace, revision)
        item = next((value for value in workspace.items if value.get("id") == item_id), None)
        if item is None:
            raise ReviewValidationError("复核对象不存在。", code="item_not_found", details={"item_id": item_id})
        if not item.get("mask_rle") or not item.get("source_window"):
            raise ReviewValidationError("当前对象没有可编辑的实例 mask。", code="mask_not_available")
        conn = _connect(self.db_url)
        try:
            row = conn.execute(
                "SELECT geotransform FROM tiffs WHERE phase_id=? AND tiff_id=?",
                (session.phase_id, session.tiff_id),
            ).fetchone()
        finally:
            conn.close()
        if row is None or not row["geotransform"]:
            raise ReviewValidationError("TIFF 缺少 geotransform，无法保存 mask。", code="missing_geotransform")
        from affine import Affine
        from .masks import apply_brush, mask_item_fields

        transform = Affine(*json.loads(row["geotransform"]))
        mask = apply_brush(item["mask_rle"], item["source_window"], strokes)
        fields = mask_item_fields(mask, item["source_window"], transform)
        return self.apply_operations(
            session_id,
            revision,
            operation_id,
            [{"type": "update", "item_id": item_id, "patch": fields}],
        )

    @staticmethod
    def _apply(workspace: ReviewWorkspace, operation: Mapping[str, Any]) -> None:
        kind = str(operation.get("type") or "")
        if kind == "add":
            item = dict(operation.get("item") or {})
            item.setdefault("id", f"item_{uuid.uuid4().hex[:12]}")
            item.setdefault("species", workspace.active_category or "")
            item.setdefault("confidence", 1.0)
            item.setdefault("source", "human")
            item.setdefault("confirmed", True)
            item.setdefault("status", "accepted")
            item.setdefault("note", "")
            _validate_box(item.get("box_px"))
            workspace.items.append(item)
            return
        if kind in {"update", "delete", "set_category", "set_note", "set_status"}:
            item_id = str(operation.get("item_id") or "")
            index = next((i for i, item in enumerate(workspace.items) if item.get("id") == item_id), None)
            if index is None:
                raise ReviewValidationError("复核对象不存在。", code="item_not_found", details={"item_id": item_id})
            frozen = is_frozen(workspace.items[index])
            if kind == "delete":
                if frozen:
                    raise ReviewValidationError(
                        "冻结框不可删除。",
                        code="frozen_item_readonly",
                        details={"item_id": item_id},
                    )
                workspace.items.pop(index)
                return
            patch = dict(operation.get("patch") or {})
            if kind == "set_category":
                patch = {"species": operation.get("species") or ""}
            elif kind == "set_note":
                patch = {"note": str(operation.get("note") or "")}
            elif kind == "set_status":
                patch = {"status": operation.get("status")}
            if frozen:
                blocked = sorted(set(patch) - FROZEN_EDITABLE_FIELDS)
                if blocked:
                    raise ReviewValidationError(
                        "冻结框仅可修改判定状态与备注。",
                        code="frozen_item_readonly",
                        details={"item_id": item_id, "fields": blocked},
                    )
            if "box_px" in patch:
                _validate_box(patch["box_px"])
            workspace.items[index] = {**workspace.items[index], **patch}
            return
        if kind == "bulk_status":
            ids = {str(value) for value in operation.get("item_ids") or []}
            status = operation.get("status")
            if status not in {"accepted", "rejected", "pending"}:
                raise ReviewValidationError("无效复核状态。", code="invalid_item_status")
            workspace.items = [{**item, "status": status} if str(item.get("id")) in ids else item for item in workspace.items]
            return
        if kind == "set_catalog":
            workspace.category_catalog = list(operation.get("categories") or [])
            known = [str(item.get("id")) for item in workspace.category_catalog if item.get("id")]
            workspace.visible_categories = known
            workspace.active_category = str(operation.get("active_category") or (known[0] if known else "")) or None
            return
        if kind == "upsert_attempt":
            attempt = dict(operation.get("attempt") or {})
            attempt_id = str(attempt.get("attempt_id") or "")
            if not attempt_id:
                raise ReviewValidationError("attempt_id 不能为空。", code="attempt_id_required")
            index = next((i for i, value in enumerate(workspace.attempts) if value.get("attempt_id") == attempt_id), None)
            if index is None:
                workspace.attempts.append(attempt)
            else:
                workspace.attempts[index] = {**workspace.attempts[index], **attempt}
            return
        if kind == "apply_attempt":
            attempt_id = str(operation.get("attempt_id") or "")
            workspace.items = list(operation.get("items") or [])
            for index, attempt in enumerate(workspace.attempts):
                if attempt.get("attempt_id") == attempt_id:
                    workspace.attempts[index] = {**attempt, "status": "applied"}
                    break
            return
        raise ReviewValidationError("不支持的复核操作。", code="unsupported_operation", details={"type": kind})


def _validate_box(value: Any) -> None:
    if not isinstance(value, list) or len(value) != 4:
        raise ReviewValidationError("检测框必须是 [x1,y1,x2,y2]。", code="invalid_box")
    try:
        x1, y1, x2, y2 = [float(v) for v in value]
    except (TypeError, ValueError) as exc:
        raise ReviewValidationError("检测框坐标必须是数字。", code="invalid_box") from exc
    if x2 <= x1 or y2 <= y1:
        raise ReviewValidationError("检测框宽高必须大于零。", code="invalid_box")


def _category_color(index: int) -> str:
    colors = ("#52c99a", "#69b1ff", "#ffc53d", "#ff7a45", "#b37feb", "#36cfc9")
    return colors[index % len(colors)]
