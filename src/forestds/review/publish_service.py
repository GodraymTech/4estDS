"""复核质量门禁与单事务发布。"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from affine import Affine
from pyproj import CRS, Transformer
from shapely.geometry import Point
from shapely.wkt import loads as load_wkt

from ..db.schema import init_db, resolve_db_path
from .domain import ReviewConflict, ReviewValidationError, workspace_summary
from .session_service import ReviewSessionService


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class ReviewPublishService:
    def __init__(
        self,
        db_url: str | None = None,
        *,
        session_service: ReviewSessionService | None = None,
        after_observations: Callable[[sqlite3.Connection, str], None] | None = None,
    ):
        self.db_url = db_url
        self.sessions = session_service or ReviewSessionService(db_url)
        self.after_observations = after_observations

    def publish(self, session_id: str) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if session.status != "active":
            raise ReviewConflict("复核会话已结束。", code="session_not_active")
        workspace = self.sessions.workspace(session_id)
        accepted = [item for item in workspace.items if item.get("status") != "rejected"]
        self._validate_items(accepted)

        init_db(self.db_url)
        conn = sqlite3.connect(resolve_db_path(self.db_url), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT rs.*, tf.active_run_id, tf.geotransform, tf.crs_epsg, tf.crs_wkt, "
                "tr.effective_geom, tr.boundary_geom "
                "FROM review_sessions rs JOIN tiffs tf ON tf.phase_id=rs.phase_id AND tf.tiff_id=rs.tiff_id "
                "JOIN tract_phases tp ON tp.tract_phase_pk=rs.tract_phase_pk "
                "JOIN tracts tr ON tr.tract_pk=tp.tract_pk WHERE rs.session_id=?",
                (session_id,),
            ).fetchone()
            if row is None or row["status"] != "active":
                raise ReviewConflict("复核会话已结束或不存在。", code="session_not_active")
            if row["revision"] != workspace.revision:
                raise ReviewConflict("复核草稿版本尚未同步。", code="revision_conflict")
            if row["active_run_id"] != row["expected_active_run_id"]:
                raise ReviewConflict(
                    "复核期间 TIFF 正式结果已变化，请重新创建会话。",
                    code="active_run_changed",
                    details={"expected": row["expected_active_run_id"], "actual": row["active_run_id"]},
                )
            self._validate_effective_area(accepted, row)

            run_id = self._run_id(conn)
            now = _now()
            metrics = {"review": workspace_summary(workspace.items), "session_id": session_id}
            conn.execute(
                "INSERT INTO runs (run_id, parent_run_id, tract_phase_pk, tiff_id, phase_id, task_type, "
                "model_arch, status, params_json, metrics_json, started_at, ended_at, duration_s, created_at) "
                "VALUES (?,?,?,?,?,'review','human_review','succeeded',?,?,?,?,0,?)",
                (
                    run_id, row["base_run_id"], row["tract_phase_pk"], row["tiff_id"], row["phase_id"],
                    json.dumps({"session_id": session_id, "revision": workspace.revision}, ensure_ascii=False),
                    json.dumps(metrics, ensure_ascii=False), now, now, now,
                ),
            )
            for item in accepted:
                self._insert_observation(conn, run_id, row, item, now)
            if self.after_observations:
                self.after_observations(conn, run_id)
            updated = conn.execute(
                "UPDATE tiffs SET active_run_id=?, inference_status='inferred', updated_at=? "
                "WHERE phase_id=? AND tiff_id=? AND active_run_id IS ?",
                (run_id, now, row["phase_id"], row["tiff_id"], row["expected_active_run_id"]),
            )
            if updated.rowcount != 1:
                raise ReviewConflict("TIFF 正式结果发生并发变化。", code="active_run_changed")
            conn.execute(
                "UPDATE review_sessions SET status='published', published_run_id=?, updated_at=? "
                "WHERE session_id=? AND status='active'",
                (run_id, now, session_id),
            )
            conn.commit()
            return {"session_id": session_id, "run_id": run_id, "observation_count": len(accepted), "status": "published"}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _validate_items(items: list[dict[str, Any]]) -> None:
        for item in items:
            species = str(item.get("species") or "").strip()
            if not species:
                raise ReviewValidationError("所有保留框必须绑定类别。", code="category_required", details={"item_id": item.get("id")})
            box = item.get("box_px")
            if not isinstance(box, list) or len(box) != 4:
                raise ReviewValidationError("检测框格式无效。", code="invalid_box", details={"item_id": item.get("id")})
            x1, y1, x2, y2 = [float(value) for value in box]
            if x2 <= x1 or y2 <= y1:
                raise ReviewValidationError("检测框宽高必须大于零。", code="invalid_box", details={"item_id": item.get("id")})
            if item.get("conflict"):
                raise ReviewValidationError("存在未解决的候选冲突。", code="unresolved_conflict", details={"item_id": item.get("id")})

    @staticmethod
    def _validate_effective_area(items: list[dict[str, Any]], row: sqlite3.Row) -> None:
        raw_geometry = row["effective_geom"] or row["boundary_geom"]
        raw_transform = row["geotransform"]
        if not raw_geometry or not raw_transform or not (row["crs_epsg"] or row["crs_wkt"]):
            return
        try:
            geometry = load_wkt(raw_geometry)
            values = json.loads(raw_transform) if isinstance(raw_transform, str) else raw_transform
            transform = Affine(*[float(value) for value in values[:6]])
            source = CRS.from_epsg(int(row["crs_epsg"])) if row["crs_epsg"] else CRS.from_wkt(row["crs_wkt"])
            converter = None if source.to_epsg() == 4326 else Transformer.from_crs(source, 4326, always_xy=True)
        except Exception:
            return
        for item in items:
            x1, y1, x2, y2 = [float(value) for value in item["box_px"]]
            x, y = transform * ((x1 + x2) / 2, (y1 + y2) / 2)
            if converter:
                x, y = converter.transform(x, y)
            if not geometry.covers(Point(x, y)):
                raise ReviewValidationError(
                    "检测框中心位于当前有效区域之外。",
                    code="outside_effective_area",
                    details={"item_id": item.get("id")},
                )

    @staticmethod
    def _run_id(conn: sqlite3.Connection) -> str:
        for _ in range(20):
            value = uuid.uuid4().hex[:6]
            if conn.execute("SELECT 1 FROM runs WHERE run_id=?", (value,)).fetchone() is None:
                return value
        raise RuntimeError("无法分配 review run_id")

    @staticmethod
    def _insert_observation(
        conn: sqlite3.Connection,
        run_id: str,
        session: sqlite3.Row,
        item: dict[str, Any],
        now: str,
    ) -> None:
        box = [float(value) for value in item["box_px"]]
        x1, y1, x2, y2 = box
        observation_id = f"obs_{uuid.uuid4().hex[:12]}"
        conn.execute(
            "INSERT INTO tree_observations "
            "(observation_id, individual_id, run_id, tract_phase_pk, tiff_id, phase_id, species, confidence, "
            "center_geom, crown_geom, box_px, box_geo, crown_width_px, crown_height_px, crown_area_px, "
            "geom_point, geom_crown, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                observation_id, item.get("individual_id"), run_id, session["tract_phase_pk"],
                session["tiff_id"], session["phase_id"], str(item["species"]).strip(),
                float(item.get("confidence") or 1.0), item.get("center_geom"), item.get("crown_geom"),
                json.dumps(box), json.dumps(item.get("box_geo")) if item.get("box_geo") is not None else None,
                x2 - x1, y2 - y1, (x2 - x1) * (y2 - y1),
                f"POINT({(x1 + x2) / 2} {(y1 + y2) / 2})", item.get("geom_crown") or item.get("crown_geom"), now,
            ),
        )
