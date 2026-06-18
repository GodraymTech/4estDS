"""观测与运行记录入库(阶段三)。

纯标准库 sqlite3,与 db/schema.py 同一套表结构。提供:
- run_logs 的开始/收尾记录(可追溯、可复现)。
- ensure_tract: 按 (acquisition_time, location) 幂等录入地块。
- write_observations: 把一次 run 的全图检测写入 tree_observations。
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from ..logging_setup import get_logger
from .schema import init_db, resolve_db_path

log = get_logger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(url: str | None) -> sqlite3.Connection:
    db_path = resolve_db_path(url)
    if not db_path.exists():
        init_db(url)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def start_run_log(
    run_id: str,
    task_type: str,
    *,
    url: str | None = None,
    model_arch: str | None = None,
    input_path: str | None = None,
    params: dict | None = None,
    tag: str | None = None,
) -> str:
    """插入一条 running 状态的 run_logs。返回 run_id。"""
    conn = _connect(url)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO run_logs "
            "(run_id, tag, task_type, model_arch, status, started_at, input_path, params_json) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (run_id, tag, task_type, model_arch, "running", _now(),
             input_path, json.dumps(params or {}, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()
    log.info(
        "run_log 开始: run_id=%s task=%s arch=%s input=%s",
        run_id, task_type, model_arch, input_path,
    )
    return run_id


def finish_run_log(
    run_id: str,
    status: str = "succeeded",
    *,
    url: str | None = None,
    metrics: dict | None = None,
    duration_s: float | None = None,
    error: str | None = None,
) -> None:
    """更新 run_logs 为终态(succeeded/failed)。"""
    conn = _connect(url)
    try:
        conn.execute(
            "UPDATE run_logs SET status=?, ended_at=?, duration_s=?, "
            "metrics_json=?, error=? WHERE run_id=?",
            (status, _now(), duration_s,
             json.dumps(metrics or {}, ensure_ascii=False), error, run_id),
        )
        if status != "succeeded":
            log.error("run_log 终态: run_id=%s status=%s error=%s", run_id, status, error)
        else:
            log.info(
                "run_log 终态: run_id=%s status=%s 耗时=%ss",
                run_id, status, f"{duration_s:.2f}" if duration_s is not None else "?",
            )
        conn.commit()
    finally:
        conn.close()


def ensure_tract(
    acquisition_time: str,
    location: str,
    *,
    url: str | None = None,
    name: str | None = None,
    pixel_w: int | None = None,
    pixel_h: int | None = None,
    gsd: float | None = None,
    geo_area: float | None = None,
    area_unit: str | None = None,
) -> str:
    """按 (acquisition_time, location) 幂等获取/创建地块,返回 tract_id。"""
    conn = _connect(url)
    try:
        row = conn.execute(
            "SELECT tract_id FROM tracts WHERE acquisition_time=? AND location=?",
            (acquisition_time, location),
        ).fetchone()
        if row:
            return row[0]
        tract_id = f"tract_{acquisition_time}_{uuid.uuid4().hex[:8]}"
        conn.execute(
            "INSERT INTO tracts "
            "(tract_id, name, acquisition_time, location, pixel_w, pixel_h, gsd, "
            " geo_area, area_unit, status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (tract_id, name, acquisition_time, location,
             pixel_w, pixel_h, gsd, geo_area, area_unit, "registered"),
        )
        if geo_area:
            log.info(
                "地块登录: %s 真实面积=%.1f%s GSD=%s",
                tract_id, geo_area, area_unit or "m2",
                f"{gsd:.4f}m" if gsd else "?",
            )
        conn.commit()
        return tract_id
    finally:
        conn.close()


def write_observations(
    tract_id: str,
    run_id: str,
    detections,
    *,
    url: str | None = None,
    slice_size: int | None = None,
) -> int:
    """将一次 run 的全图检测(已 WBF 去重)写入 tree_observations。返回写入条数。

    detections: 可迭代的 Detection(含 x1,y1,x2,y2,score,label,center)。
    box 以 JSON 文本存 box_px_full;几何/地理坐标待仿射变换接入(TODO)。
    """
    conn = _connect(url)
    n = 0
    try:
        for d in detections:
            obs_id = f"obs_{uuid.uuid4().hex[:12]}"
            cx, cy = d.center
            conn.execute(
                "INSERT INTO tree_observations "
                "(obs_id, tract_id, run_id, species, confidence, box_px_full, "
                " crown_w_px, crown_h_px, crown_area_px, geom_point, slice_size) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (obs_id, tract_id, run_id, d.label, d.score,
                 json.dumps([d.x1, d.y1, d.x2, d.y2]),
                 d.width, d.height, d.width * d.height,
                 f"POINT({cx} {cy})", slice_size),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    log.info(
        "写入观测: %d 条 -> tract_id=%s run_id=%s slice_size=%s",
        n, tract_id, run_id, slice_size,
    )
    return n


def count_observations(run_id: str, *, url: str | None = None) -> int:
    """查询某 run 的观测条数(供测试/CLI 汇报)。"""
    conn = _connect(url)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM tree_observations WHERE run_id=?", (run_id,)
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()
