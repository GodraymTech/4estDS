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
            extra = getattr(d, "extra", None) or {}
            height = extra.get("height")
            height_source = extra.get("height_source")
            conn.execute(
                "INSERT INTO tree_observations "
                "(obs_id, tract_id, run_id, species, confidence, box_px_full, "
                " crown_w_px, crown_h_px, crown_area_px, height, height_source, "
                " geom_point, slice_size) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (obs_id, tract_id, run_id, d.label, d.score,
                 json.dumps([d.x1, d.y1, d.x2, d.y2]),
                 d.width, d.height, d.width * d.height,
                 height, height_source,
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


def register_source(
    tract_id: str,
    source_type: str,
    path: str,
    *,
    meta: dict | None = None,
    url: str | None = None,
) -> str:
    """登记地块的一个多源文件(RGB/CHM/DSM/DEM/多光谱)。

    按 (tract_id, source_type, path) 幂等: 已存在则返回原 source_id。
    """
    conn = _connect(url)
    try:
        row = conn.execute(
            "SELECT source_id FROM tract_sources "
            "WHERE tract_id=? AND source_type=? AND path=?",
            (tract_id, source_type, path),
        ).fetchone()
        if row:
            return row[0]
        source_id = f"src_{uuid.uuid4().hex[:10]}"
        conn.execute(
            "INSERT INTO tract_sources (source_id, tract_id, source_type, path, meta_json) "
            "VALUES (?,?,?,?,?)",
            (source_id, tract_id, source_type, path,
             json.dumps(meta, ensure_ascii=False) if meta else None),
        )
        conn.commit()
        log.info("多源登记: tract=%s type=%s path=%s", tract_id, source_type, path)
        return source_id
    finally:
        conn.close()


def parse_point(wkt: str | None) -> tuple[float, float] | None:
    """解析 'POINT(cx cy)' 文本为 (x, y);无法解析返回 None。"""
    if not wkt or not isinstance(wkt, str):
        return None
    s = wkt.strip()
    if "(" not in s or ")" not in s:
        return None
    try:
        inner = s[s.index("(") + 1: s.index(")")]
        parts = inner.replace(",", " ").split()
        return float(parts[0]), float(parts[1])
    except (ValueError, IndexError):
        return None


def consolidate_tract_trees(
    tract_id: str,
    run_id: str,
    observations,
    *,
    url: str | None = None,
) -> int:
    """将某 run 的观测整理为地块规范单木 tract_trees(幂等: 先清空该地块再重建)。

    observations: fetch_observations 返回的 dict 列表
    (含 obs_id/geom_point/geom_crown/height/crown_area_px/species/confidence)。
    返回写入的规范株条数。保留已有 individual_id 链接(重建后由 persist_individuals 回填)。
    """
    conn = _connect(url)
    n = 0
    try:
        conn.execute("DELETE FROM tract_trees WHERE tract_id=?", (tract_id,))
        for o in observations:
            canonical_id = f"ct_{uuid.uuid4().hex[:12]}"
            conn.execute(
                "INSERT INTO tract_trees "
                "(canonical_id, tract_id, individual_id, species, confidence, "
                " geom_point, geom_crown, height, crown, chosen_obs_id, active_run_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (canonical_id, tract_id, None, o.get("species"), o.get("confidence"),
                 o.get("geom_point"), o.get("geom_crown"),
                 o.get("height"), o.get("crown_area_px"),
                 o.get("obs_id"), run_id),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    log.info("规范单木整理: %d 株 -> tract_id=%s run_id=%s", n, tract_id, run_id)
    return n


def persist_individuals(individuals, *, url: str | None = None) -> int:
    """写入跨时相个体 tree_individuals,并按 chosen_obs_id 回填 tract_trees.individual_id。

    individuals: dict 列表,每项含 individual_id/location_cluster/first_seen/last_seen/
    status/growth_json(str)/members(dict: time->obs_key)。返回写入的个体数。
    """
    conn = _connect(url)
    n = 0
    linked = 0
    try:
        for ind in individuals:
            conn.execute(
                "INSERT INTO tree_individuals "
                "(individual_id, location_cluster, first_seen, last_seen, status, growth_json) "
                "VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(individual_id) DO UPDATE SET "
                " location_cluster=excluded.location_cluster, first_seen=excluded.first_seen, "
                " last_seen=excluded.last_seen, status=excluded.status, growth_json=excluded.growth_json",
                (ind["individual_id"], ind.get("location_cluster"), ind.get("first_seen"),
                 ind.get("last_seen"), ind.get("status"), ind.get("growth_json")),
            )
            n += 1
            for _time, obs_key in (ind.get("members") or {}).items():
                cur = conn.execute(
                    "UPDATE tract_trees SET individual_id=? WHERE chosen_obs_id=?",
                    (ind["individual_id"], obs_key),
                )
                if cur.rowcount and cur.rowcount > 0:
                    linked += cur.rowcount
        conn.commit()
    finally:
        conn.close()
    log.info("个体持久化: %d 个体, 回填规范株 %d 条", n, linked)
    return n
