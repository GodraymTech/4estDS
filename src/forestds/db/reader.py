"""Read helpers for the tract -> phase -> TIFF -> observation schema."""
from __future__ import annotations

import json
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


def _loads(raw: str | None, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _latest_path(raw: str | None) -> str | None:
    data = _loads(raw, {})
    if not isinstance(data, dict) or not data:
        return None
    key = sorted(str(k) for k in data.keys())[-1]
    return data.get(key)


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


def _base_tract_query(where: str = "") -> str:
    return (
        "SELECT tr.tract_pk, tr.region_id, tr.city, tr.county, tr.town, tr.tract_id, tr.boundary_geom, tr.boundary_source, "
        "tr.coverage_status AS tract_coverage_status, tr.notes, tr.created_at, tr.updated_at, "
        "tp.tract_phase_pk, tp.phase_id, tp.coverage_status, tp.active_run_id, "
        "tf.tiff_id, tf.file_name, tf.path_versions, tf.multisource_path_versions, "
        "tf.footprint_geom, tf.footprint_bbox, tf.crs_epsg, tf.crs_wkt, tf.geotransform, "
        "tf.pixel_width, tf.pixel_height, tf.gsd, tf.geo_area, tf.area_unit, tf.band_count, "
        "tf.dtype, tf.nodata, tf.inference_status "
        "FROM tracts tr "
        "LEFT JOIN tract_phases tp ON tp.tract_phase_pk = ("
        "  SELECT tp2.tract_phase_pk FROM tract_phases tp2 "
        "  WHERE tp2.tract_pk = tr.tract_pk "
        "  ORDER BY (tp2.active_run_id IS NOT NULL) DESC, tp2.phase_id DESC LIMIT 1"
        ") "
        "LEFT JOIN tiffs tf ON tf.rowid = ("
        "  SELECT tf2.rowid FROM tiffs tf2 "
        "  WHERE tf2.tract_phase_pk = tp.tract_phase_pk "
        "  ORDER BY tf2.created_at DESC LIMIT 1"
        ") "
        f"{where}"
    )


def _phase_tract_query(where: str = "") -> str:
    return (
        "SELECT tr.tract_pk, tr.region_id, tr.city, tr.county, tr.town, tr.tract_id, tr.boundary_geom, tr.boundary_source, "
        "tr.coverage_status AS tract_coverage_status, tr.notes, tr.created_at, tr.updated_at, "
        "tp.tract_phase_pk, tp.phase_id, tp.coverage_status, tp.active_run_id, "
        "tf.tiff_id, tf.file_name, tf.path_versions, tf.multisource_path_versions, "
        "tf.footprint_geom, tf.footprint_bbox, tf.crs_epsg, tf.crs_wkt, tf.geotransform, "
        "tf.pixel_width, tf.pixel_height, tf.gsd, tf.geo_area, tf.area_unit, tf.band_count, "
        "tf.dtype, tf.nodata, tf.inference_status "
        "FROM tract_phases tp "
        "JOIN tracts tr ON tr.tract_pk = tp.tract_pk "
        "LEFT JOIN tiffs tf ON tf.rowid = ("
        "  SELECT tf2.rowid FROM tiffs tf2 "
        "  WHERE tf2.tract_phase_pk = tp.tract_phase_pk "
        "  ORDER BY tf2.created_at DESC LIMIT 1"
        ") "
        f"{where}"
    )


def _tract_row(row: dict) -> dict:
    out = dict(row)
    out["status"] = out.get("coverage_status") or out.get("tract_coverage_status")
    out["source_path"] = _latest_path(out.get("path_versions"))
    return out


def _latest_run_for_tract_conn(conn: sqlite3.Connection, tract_id: str) -> str | None:
    row = conn.execute(
        "SELECT o.run_id FROM tree_observations o "
        "JOIN runs r ON r.run_id = o.run_id "
        "JOIN tract_phases tp ON tp.tract_phase_pk = o.tract_phase_pk "
        "WHERE (tp.tract_id=? OR tp.tract_phase_pk=?) AND r.status='succeeded' "
        "ORDER BY r.started_at DESC LIMIT 1",
        (tract_id, tract_id),
    ).fetchone()
    return row["run_id"] if row else None


def _mean_observation_center(
    conn: sqlite3.Connection,
    tract: dict,
) -> tuple[float, float] | None:
    tract_key = tract.get("tract_phase_pk") or tract.get("tract_id")
    if not tract_key:
        return None
    run_id = tract.get("active_run_id") or _latest_run_for_tract_conn(conn, tract_key)
    sql = (
        "SELECT o.center_geom FROM tree_observations o "
        "JOIN tract_phases tp ON tp.tract_phase_pk=o.tract_phase_pk "
        "WHERE (tp.tract_id=? OR tp.tract_phase_pk=?) AND o.center_geom IS NOT NULL"
    )
    params: list[str] = [tract_key, tract_key]
    if run_id:
        sql += " AND o.run_id=?"
        params.append(run_id)
    points = []
    for row in conn.execute(sql, params).fetchall():
        pt = _parse_wkt_point(row["center_geom"])
        if isinstance(pt, tuple) and len(pt) == 2:
            points.append(pt)
    if not points:
        return None
    x = sum(p[0] for p in points) / len(points)
    y = sum(p[1] for p in points) / len(points)
    return _to_wgs84(x, y, tract)


def _enrich_tracts(conn: sqlite3.Connection, tracts: list[dict]) -> list[dict]:
    for tract in tracts:
        tract_key = tract.get("tract_phase_pk") or tract.get("tract_id")
        run_id = None
        if tract_key:
            run_id = tract.get("active_run_id") or _latest_run_for_tract_conn(conn, tract_key)
            if run_id and not tract.get("active_run_id"):
                tract["active_run_id"] = run_id
            row_count = conn.execute(
                "SELECT COUNT(*) AS c FROM tree_observations o "
                "JOIN tract_phases tp ON tp.tract_phase_pk=o.tract_phase_pk "
        "WHERE (tp.tract_id=? OR tp.tract_phase_pk=?)"
        + (" AND o.run_id=?" if run_id else ""),
                (tract_key, tract_key, run_id) if run_id else (tract_key, tract_key),
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
    """取单个地块元信息。支持 tract_id 或 tract_pk。"""
    conn = _connect(url)
    try:
        row = conn.execute(
            _phase_tract_query("WHERE tp.tract_phase_pk=? LIMIT 1"),
            (tract_id,),
        ).fetchone()
        if row:
            tracts = _enrich_tracts(conn, [_tract_row(dict(row))])
            return tracts[0] if tracts else None
        row = conn.execute(
            _base_tract_query("WHERE tr.tract_id=? OR tr.tract_pk=? LIMIT 1"),
            (tract_id, tract_id),
        ).fetchone()
        tracts = _enrich_tracts(conn, [_tract_row(dict(row))]) if row else []
    finally:
        conn.close()
    return tracts[0] if tracts else None


def latest_run_for_tract(tract_id: str, *, url: str | None = None) -> str | None:
    """返回地块最近一次有观测的成功 run_id。"""
    conn = _connect(url)
    try:
        return _latest_run_for_tract_conn(conn, tract_id)
    finally:
        conn.close()


def _observation_row(row: dict) -> dict:
    out = dict(row)
    out["geom_crown"] = out.get("geom_crown") or out.get("crown_geom")
    out["crown_area_geo"] = out.get("crown_area_geo_real") or out.get("crown_area_geo_est")
    out["crown_volume_geo"] = out.get("crown_volume_geo_real") or out.get("crown_volume_geo_est")
    return out


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
        clauses.append("o.run_id=?")
        params.append(run_id)
    if tract_id:
        clauses.append("(tp.tract_id=? OR tp.tract_phase_pk=?)")
        params.extend([tract_id, tract_id])
    where = " AND ".join(clauses)
    conn = _connect(url)
    try:
        rows = conn.execute(
            "SELECT o.*, tp.tract_id, tp.region_id FROM tree_observations o "
            "JOIN tract_phases tp ON tp.tract_phase_pk=o.tract_phase_pk "
            f"WHERE {where}",
            params,
        ).fetchall()
    finally:
        conn.close()
    obs = [_observation_row(dict(row)) for row in rows]
    log.debug("fetch_observations: {} 条 (run_id={} tract_id={})", len(obs), run_id, tract_id)
    return obs


def get_run(run_id: str, *, url: str | None = None) -> dict | None:
    conn = _connect(url)
    try:
        row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def list_runs(
    *,
    url: str | None = None,
    task_type: str | None = None,
    limit: int = 50,
) -> list[dict]:
    conn = _connect(url)
    try:
        bounded_limit = max(1, min(int(limit), 200))
        select_sql = (
            "SELECT r.*, "
            "(SELECT COUNT(*) FROM tree_observations o WHERE o.run_id=r.run_id) AS observation_count, "
            "tp.tract_id, tf.geo_area, tf.area_unit "
            "FROM runs r "
            "LEFT JOIN tract_phases tp ON tp.tract_phase_pk = r.tract_phase_pk "
            "LEFT JOIN tiffs tf ON tf.rowid = ("
            "  SELECT tf2.rowid FROM tiffs tf2 WHERE tf2.tract_phase_pk=r.tract_phase_pk ORDER BY tf2.created_at DESC LIMIT 1"
            ") "
        )
        if task_type:
            rows = conn.execute(
                select_sql + "WHERE r.task_type=? ORDER BY r.started_at DESC LIMIT ?",
                (task_type, bounded_limit),
            ).fetchall()
        else:
            rows = conn.execute(select_sql + "ORDER BY r.started_at DESC LIMIT ?", (bounded_limit,)).fetchall()
    finally:
        conn.close()
    return _rows_to_dicts(rows)


def tract_for_run(run_id: str, *, url: str | None = None) -> str | None:
    conn = _connect(url)
    try:
        row = conn.execute(
            "SELECT tp.tract_id FROM runs r "
            "LEFT JOIN tract_phases tp ON tp.tract_phase_pk=r.tract_phase_pk "
            "WHERE r.run_id=?",
            (run_id,),
        ).fetchone()
        if row and row["tract_id"]:
            return row["tract_id"]
        row = conn.execute(
            "SELECT tp.tract_id FROM tree_observations o "
            "JOIN tract_phases tp ON tp.tract_phase_pk=o.tract_phase_pk "
            "WHERE o.run_id=? LIMIT 1",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    return row["tract_id"] if row else None


def list_tracts(*, url: str | None = None) -> list[dict]:
    conn = _connect(url)
    try:
        rows = conn.execute(_phase_tract_query("ORDER BY tp.phase_id DESC, tr.tract_id")).fetchall()
        tracts = _enrich_tracts(conn, [_tract_row(dict(row)) for row in rows])
    finally:
        conn.close()
    return tracts


def find_cached_tiles(input_path: str, *, url: str | None = None) -> Path | None:
    """查找该图像最近一次成功运行保留的切片目录。"""
    p = Path(input_path)
    resolved = str(p.resolve())
    filename = p.name

    conn = _connect(url)
    try:
        row = conn.execute(
            "SELECT run_id, tiles_dir FROM runs "
            "WHERE status='succeeded' AND tiles_dir IS NOT NULL "
            "AND (input_path=? OR input_path LIKE ?) "
            "ORDER BY CASE WHEN input_path=? THEN 0 ELSE 1 END, started_at DESC LIMIT 1",
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
        row = conn.execute(
            "SELECT active_run_id FROM tract_phases "
            "WHERE (tract_id=? OR tract_phase_pk=?) AND active_run_id IS NOT NULL "
            "ORDER BY phase_id DESC LIMIT 1",
            (tract_id, tract_id),
        ).fetchone()
    finally:
        conn.close()
    return row["active_run_id"] if row else None


def latest_tiff_path_for_tract(tract_id: str, *, url: str | None = None) -> str | None:
    conn = _connect(url)
    try:
        row = conn.execute(
            "SELECT tf.path_versions FROM tiffs tf "
            "JOIN tract_phases tp ON tp.tract_phase_pk=tf.tract_phase_pk "
            "WHERE (tp.tract_id=? OR tp.tract_phase_pk=?) ORDER BY tp.phase_id DESC, tf.updated_at DESC LIMIT 1",
            (tract_id, tract_id),
        ).fetchone()
    finally:
        conn.close()
    return _latest_path(row["path_versions"]) if row else None
