"""读取层（阶段六）：为统计报告 / 导出提供查询。

纯标准库 sqlite3，返回普通 dict（与 ORM 解耦，保证无重依赖可跑）。
与 writer.py 对称： writer 管写、reader 管读。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from loguru import logger as log
from .schema import init_db, resolve_db_path


def _connect(url: str | None) -> sqlite3.Connection:
    db_path: Path = resolve_db_path(url)
    init_db(url)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


def _parse_wkt_point(wkt: str | None) -> tuple[float, float] | None:
    if not wkt or not isinstance(wkt, str) or "POINT" not in wkt.upper():
        return None
    try:
        inner = wkt[wkt.index("(") + 1: wkt.rindex(")")]
        parts = inner.replace(",", " ").split()
        return float(parts[0]), float(parts[1])
    except (ValueError, IndexError):
        return None


def _looks_like_lnglat(x: float, y: float) -> bool:
    return -180 <= x <= 180 and -90 <= y <= 90


def _to_wgs84(x: float, y: float, tract: dict) -> tuple[float, float] | None:
    if tract.get("crs_epsg") == 4326 or _looks_like_lnglat(x, y):
        return x, y

    crs_epsg = tract.get("crs_epsg")
    crs_wkt = tract.get("crs_wkt")
    if not crs_epsg and not crs_wkt:
        return None

    try:
        from rasterio.crs import CRS
        from rasterio.warp import transform

        src_crs = CRS.from_epsg(int(crs_epsg)) if crs_epsg else CRS.from_wkt(crs_wkt)
        lngs, lats = transform(src_crs, "EPSG:4326", [x], [y])
        lng, lat = float(lngs[0]), float(lats[0])
        if _looks_like_lnglat(lng, lat):
            return lng, lat
    except Exception as exc:  # noqa: BLE001
        log.debug("地块中心点坐标转换失败: tract={} err={}", tract.get("tract_id"), exc)
    return None


def _latest_run_for_tract_conn(conn: sqlite3.Connection, tract_id: str) -> str | None:
    row = conn.execute(
        "SELECT o.run_id FROM tree_observations o "
        "JOIN run_logs r ON r.run_id = o.run_id "
        "WHERE o.tract_id=? AND r.status='succeeded' ORDER BY r.started_at DESC LIMIT 1",
        (tract_id,),
    ).fetchone()
    return row["run_id"] if row else None


def _mean_observation_center(
    conn: sqlite3.Connection,
    tract: dict,
) -> tuple[float, float] | None:
    tract_id = tract.get("tract_id")
    if not tract_id:
        return None
    run_id = tract.get("active_run_id") or _latest_run_for_tract_conn(conn, tract_id)
    sql = "SELECT center_geo FROM tree_observations WHERE tract_id=? AND center_geo IS NOT NULL"
    params: list[str] = [tract_id]
    if run_id:
        sql += " AND run_id=?"
        params.append(run_id)
    points = []
    for row in conn.execute(sql, params).fetchall():
        pt = _parse_wkt_point(row["center_geo"])
        if pt:
            points.append(pt)
    if not points:
        return None
    x = sum(p[0] for p in points) / len(points)
    y = sum(p[1] for p in points) / len(points)
    return _to_wgs84(x, y, tract)


def _enrich_tracts(conn: sqlite3.Connection, tracts: list[dict]) -> list[dict]:
    for tract in tracts:
        tract_id = tract.get("tract_id")
        run_id = None
        if tract_id:
            run_id = tract.get("active_run_id") or _latest_run_for_tract_conn(conn, tract_id)
            if run_id and not tract.get("active_run_id"):
                tract["active_run_id"] = run_id
            row_count = conn.execute(
                "SELECT COUNT(*) AS c FROM tree_observations WHERE tract_id=?"
                + (" AND run_id=?" if run_id else ""),
                (tract_id, run_id) if run_id else (tract_id,),
            ).fetchone()
            tract["observation_count"] = int(row_count["c"]) if row_count else 0
        if tract.get("center_lng") is not None and tract.get("center_lat") is not None:
            continue
        center = _mean_observation_center(conn, tract)
        if center:
            tract["center_lng"] = center[0]
            tract["center_lat"] = center[1]
    return tracts


def get_tract(tract_id: str, *, url: str | None = None) -> dict | None:
    """取单个地块元信息。"""
    conn = _connect(url)
    try:
        row = conn.execute(
            "SELECT * FROM tracts WHERE tract_id=?", (tract_id,)
        ).fetchone()
        tracts = _enrich_tracts(conn, [dict(row)]) if row else []
    finally:
        conn.close()
    return tracts[0] if tracts else None


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(
        row["name"] == column
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    )


def resolve_tract_id(
    *,
    tract_id: str | None = None,
    acquisition_time: str | None = None,
    location: str | None = None,
    url: str | None = None,
) -> str | None:
    """按 tract_id 或 (acquisition_time, location) 定位地块。"""
    if tract_id:
        return tract_id
    if not (acquisition_time and location):
        return None
    conn = _connect(url)
    try:
        row = conn.execute(
            "SELECT tract_id FROM tracts WHERE acquisition_time=? AND location=?",
            (acquisition_time, location),
        ).fetchone()
    finally:
        conn.close()
    return row["tract_id"] if row else None


def latest_run_for_tract(tract_id: str, *, url: str | None = None) -> str | None:
    """返回地块最近一次有观测的 run_id。"""
    conn = _connect(url)
    try:
        row = conn.execute(
            "SELECT o.run_id FROM tree_observations o "
            "JOIN run_logs r ON r.run_id = o.run_id "
            "WHERE o.tract_id=? AND r.status='succeeded' ORDER BY r.started_at DESC LIMIT 1",
            (tract_id,),
        ).fetchone()
    finally:
        conn.close()
    return row["run_id"] if row else None


def fetch_observations(
    *,
    run_id: str | None = None,
    tract_id: str | None = None,
    url: str | None = None,
) -> list[dict]:
    """拉取观测记录。run_id / tract_id 至少传一个（可共同限定）。"""
    if not run_id and not tract_id:
        raise ValueError("fetch_observations 需要 run_id 或 tract_id")
    clauses, params = [], []
    if run_id:
        clauses.append("run_id=?")
        params.append(run_id)
    if tract_id:
        clauses.append("tract_id=?")
        params.append(tract_id)
    where = " AND ".join(clauses)
    conn = _connect(url)
    try:
        rows = conn.execute(
            f"SELECT * FROM tree_observations WHERE {where}", params
        ).fetchall()
    finally:
        conn.close()
    obs = _rows_to_dicts(rows)
    for o in obs:
        if "crown_area_px" not in o or o["crown_area_px"] is None:
            o["crown_area_px"] = o.get("crown_area_px_real")
        if "crown_area_geo" not in o or o["crown_area_geo"] is None:
            o["crown_area_geo"] = o.get("crown_area_geo_real")
        if "crown_volume_geo" not in o or o["crown_volume_geo"] is None:
            o["crown_volume_geo"] = o.get("crown_volume_geo_real")
    log.debug("fetch_observations: {} 条 (run_id={} tract_id={})", len(obs), run_id, tract_id)
    return obs


def get_run(run_id: str, *, url: str | None = None) -> dict | None:
    conn = _connect(url)
    try:
        row = conn.execute(
            "SELECT * FROM run_logs WHERE run_id=?", (run_id,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def list_tracts(*, url: str | None = None) -> list[dict]:
    conn = _connect(url)
    try:
        rows = conn.execute(
            "SELECT * FROM tracts ORDER BY acquisition_time DESC, location"
        ).fetchall()
        tracts = _enrich_tracts(conn, _rows_to_dicts(rows))
    finally:
        conn.close()
    return tracts


def find_cached_tiles(input_path: str, *, url: str | None = None) -> Path | None:
    """查找该图像最近一次成功运行保留的切片目录。

    匹配策略（优先级递降）：
    1. 精确路径匹配：input_path 完全一致（最可靠）
    2. 文件名匹配：路径可能变化，但文件名（stem+suffix）不变

    直接从 run_logs.tiles_dir 列读取，无需文件系统 glob。
    若目录在磁盘上已被删除，返回 None（不信任幽灵记录）。
    """
    p = Path(input_path)
    resolved = str(p.resolve())
    filename = p.name  # e.g. "forest_rgb.tif"

    conn = _connect(url)
    try:
        row = conn.execute(
            "SELECT run_id, tiles_dir FROM run_logs "
            "WHERE status='succeeded' AND tiles_dir IS NOT NULL "
            "AND (input_path=? OR input_path LIKE ?) "
            "ORDER BY "
            "  CASE WHEN input_path=? THEN 0 ELSE 1 END, "  # 精确路径优先
            "  started_at DESC LIMIT 1",
            (resolved, f"%/{filename}", resolved),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return None
    td = Path(row["tiles_dir"])
    if td.is_dir() and any(td.glob("*.*")):
        log.warning("命中切片缓存, 无需执行切割: run_id={} tiles_dir={}", row["run_id"], td)
        return td
    log.warning("缓存记录存在变动，但目录已失效: {}", td)
    return None


def active_run_for_tract(tract_id: str, *, url: str | None = None) -> str | None:
    """返回地块当前激活/发布的 run_id。"""
    conn = _connect(url)
    try:
        if not _has_column(conn, "tracts", "active_run_id"):
            return None
        row = conn.execute(
            "SELECT active_run_id FROM tracts WHERE tract_id=?",
            (tract_id,),
        ).fetchone()
    finally:
        conn.close()
    return row["active_run_id"] if row else None
