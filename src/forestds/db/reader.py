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


def _parse_wkt_polygon_centroid(wkt: str | None) -> tuple[float, float] | None:
    if not wkt or "POLYGON" not in wkt.upper() or "EMPTY" in wkt.upper():
        return None
    try:
        inner = wkt[wkt.index("((") + 2 : wkt.rindex("))")]
        coords: list[tuple[float, float]] = []
        for item in inner.split(","):
            parts = item.strip().split()
            if len(parts) >= 2:
                coords.append((float(parts[0]), float(parts[1])))
        if len(coords) > 1 and coords[0] == coords[-1]:
            coords = coords[:-1]
        if not coords:
            return None
        if len(coords) < 3:
            return (
                sum(p[0] for p in coords) / len(coords),
                sum(p[1] for p in coords) / len(coords),
            )
        pts = coords + [coords[0]]
        signed_area = 0.0
        cx = 0.0
        cy = 0.0
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            cross = x0 * y1 - x1 * y0
            signed_area += cross
            cx += (x0 + x1) * cross
            cy += (y0 + y1) * cross
        if abs(signed_area) < 1e-12:
            return (
                sum(p[0] for p in coords) / len(coords),
                sum(p[1] for p in coords) / len(coords),
            )
        area = signed_area * 0.5
        return cx / (6 * area), cy / (6 * area)
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
        "SELECT tr.tract_pk, tr.region_id, tr.city, tr.county, tr.town, tr.tract_id, tr.boundary_geom, tr.boundary_geom_cent, "
        "tr.effective_geom, tr.effective_area_hm2, tr.effective_source, tf.area_hm2 AS tiff_effective_area_hm2, "
        "tr.coverage_status AS tract_coverage_status, tr.notes, tr.created_at, tr.updated_at, "
        "tp.tract_phase_pk, tp.phase_id, tr.coverage_status, tf.active_run_id, "
        "tf.tiff_id, tf.file_name, tf.path_versions, tf.multisource_path_versions, "
        "tf.tiff_type, tf.footprint_geom, tf.footprint_bbox, tf.center_geom, tf.crs_epsg, tf.crs_wkt, tf.geotransform, "
        "tf.pixel_width, tf.pixel_height, tf.gsd, tf.footprint_area_hm2, tf.area_hm2, tf.band_count, "
        "tf.dtype, tf.nodata, tf.inference_status "
        "FROM tracts tr "
        "LEFT JOIN tract_phases tp ON tp.tract_phase_pk = ("
        "  SELECT tp2.tract_phase_pk FROM tract_phases tp2 "
        "  WHERE tp2.tract_pk = tr.tract_pk "
        "  ORDER BY EXISTS(SELECT 1 FROM tiffs tf3 WHERE tf3.tract_phase_pk=tp2.tract_phase_pk AND tf3.active_run_id IS NOT NULL) DESC, "
        "  tp2.phase_id DESC LIMIT 1"
        ") "
        "LEFT JOIN tiffs tf ON tf.rowid = ("
        "  SELECT tf2.rowid FROM tiffs tf2 "
        "  WHERE tf2.tract_phase_pk = tp.tract_phase_pk "
        "  ORDER BY (tf2.active_run_id IS NOT NULL) DESC, tf2.created_at DESC LIMIT 1"
        ") "
        f"{where}"
    )


def _phase_tract_query(where: str = "") -> str:
    return (
        "SELECT tr.tract_pk, tr.region_id, tr.city, tr.county, tr.town, tr.tract_id, tr.boundary_geom, tr.boundary_geom_cent, "
        "tr.effective_geom, tr.effective_area_hm2, tr.effective_source, tf.area_hm2 AS tiff_effective_area_hm2, "
        "tr.coverage_status AS tract_coverage_status, tr.notes, tr.created_at, tr.updated_at, "
        "tp.tract_phase_pk, tp.phase_id, tp.area_hm2 AS tract_phase_area_hm2, tr.coverage_status, tf.active_run_id, "
        "tf.tiff_id, tf.file_name, tf.path_versions, tf.multisource_path_versions, "
        "tf.tiff_type, tf.footprint_geom, tf.footprint_bbox, tf.center_geom, tf.crs_epsg, tf.crs_wkt, tf.geotransform, "
        "tf.pixel_width, tf.pixel_height, tf.gsd, tf.footprint_area_hm2, tf.area_hm2, tf.band_count, "
        "tf.dtype, tf.nodata, tf.inference_status "
        "FROM tract_phases tp "
        "JOIN tracts tr ON tr.tract_pk = tp.tract_pk "
        "LEFT JOIN tiffs tf ON tf.rowid = ("
        "  SELECT tf2.rowid FROM tiffs tf2 "
        "  WHERE tf2.tract_phase_pk = tp.tract_phase_pk "
        "  ORDER BY (tf2.active_run_id IS NOT NULL) DESC, tf2.created_at DESC LIMIT 1"
        ") "
        f"{where}"
    )


def _tract_row(row: dict) -> dict:
    out = dict(row)
    out["status"] = out.get("coverage_status") or out.get("tract_coverage_status")
    out["source_path"] = _latest_path(out.get("path_versions"))
    center = _parse_wkt_point(out.get("center_geom")) or _parse_wkt_polygon_centroid(out.get("boundary_geom")) or _parse_wkt_point(out.get("boundary_geom_cent"))
    if center:
        out["center_lng"], out["center_lat"] = center[0], center[1]
    else:
        out["center_lng"], out["center_lat"] = None, None
    if out.get("footprint_area_hm2") is not None:
        out["geo_area"] = float(out["footprint_area_hm2"]) * 10000.0
    try:
        from shapely.wkt import loads as load_wkt
        from ..effective_area.service import geodesic_area_hm2

        boundary_area = (
            geodesic_area_hm2(load_wkt(out["boundary_geom"]))
            if out.get("boundary_geom")
            else None
        )
    except Exception:
        boundary_area = None
    db_effective = out.get("effective_area_hm2")
    db_tract = out.get("tract_area_hm2")
    if db_tract is None:
        out["tract_area_hm2"] = boundary_area
    out["effective_area_m2"] = (
        float(db_effective) * 10_000.0
        if db_effective is not None
        else None
    )
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
    return row[0] if row else None


def _mean_observation_center(
    conn: sqlite3.Connection,
    tract: dict,
) -> tuple[float, float] | None:
    tract_key = tract.get("tract_phase_pk") or tract.get("tract_id")
    if not tract_key:
        return None
    sql = (
        "SELECT o.center_geom FROM tree_observations o "
        "JOIN tract_phases tp ON tp.tract_phase_pk=o.tract_phase_pk "
        "JOIN tiffs tf ON tf.active_run_id=o.run_id "
        "WHERE (tp.tract_id=? OR tp.tract_phase_pk=?) AND o.center_geom IS NOT NULL"
    )
    params: list[str] = [tract_key, tract_key]
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
        if tract_key:
            row_count = conn.execute(
                "SELECT COUNT(*) AS c FROM tree_observations o "
                "JOIN tract_phases tp ON tp.tract_phase_pk=o.tract_phase_pk "
                "JOIN tiffs tf ON tf.active_run_id=o.run_id "
                "WHERE (tp.tract_id=? OR tp.tract_phase_pk=?)",
                (tract_key, tract_key),
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
    out["crown_area_geo"] = out.get("crown_area_geo_real") or out.get("crown_area_geo_est")
    out["crown_volume_geo"] = out.get("crown_volume_geo_real") or out.get("crown_volume_geo_est")
    return out


def _filter_effective_observations(observations: list[dict]) -> list[dict]:
    """按当前地块有效区域执行中心点过滤；缺少可靠地理点时保守保留。"""
    if not observations:
        return observations
    from shapely.geometry import Point
    from shapely.prepared import prep
    from shapely.wkt import loads as load_wkt

    geometries: dict[str, object] = {}
    # None 表示源 CRS 已是 WGS84；False 表示 CRS 无法解析，必须保守保留记录。
    transformers: dict[tuple[object, object], object | None | bool] = {}
    kept: list[dict] = []
    for item in observations:
        raw_geometry = item.get("_effective_geom") or item.get("_boundary_geom")
        center = _parse_wkt_point(item.get("center_geom"))
        if not raw_geometry or center is None:
            for key in ("_effective_geom", "_boundary_geom", "_crs_epsg", "_crs_wkt"):
                item.pop(key, None)
            kept.append(item)
            continue
        prepared = geometries.get(raw_geometry)
        if prepared is None:
            try:
                geometry = load_wkt(raw_geometry)
                if geometry.is_empty:
                    raise ValueError("empty geometry")
                prepared = prep(geometry)
                geometries[raw_geometry] = prepared
            except Exception:  # noqa: BLE001
                for key in ("_effective_geom", "_boundary_geom", "_crs_epsg", "_crs_wkt"):
                    item.pop(key, None)
                kept.append(item)
                continue
        epsg = item.get("_crs_epsg")
        crs_wkt = item.get("_crs_wkt")
        if not epsg and not crs_wkt:
            center = None
        elif (epsg and int(epsg) != 4326) or (not epsg and crs_wkt):
            transformer_key = (epsg, crs_wkt)
            if transformer_key not in transformers:
                try:
                    from pyproj import CRS, Transformer

                    source = CRS.from_epsg(int(epsg)) if epsg else CRS.from_wkt(str(crs_wkt))
                    transformers[transformer_key] = (
                        None
                        if source.to_epsg() == 4326
                        else Transformer.from_crs(source, 4326, always_xy=True)
                    )
                except Exception:  # noqa: BLE001
                    transformers[transformer_key] = False
            transformer = transformers[transformer_key]
            if transformer is False:
                center = None
            elif transformer is not None:
                try:
                    center = transformer.transform(*center)
                except Exception:  # noqa: BLE001
                    center = None
        keep = center is None or bool(prepared.covers(Point(*center)))
        for key in ("_effective_geom", "_boundary_geom", "_crs_epsg", "_crs_wkt"):
            item.pop(key, None)
        if keep:
            kept.append(item)
    return kept


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
        clauses.append("(tp.tract_id=? OR tp.tract_phase_pk=? OR tp.tract_pk=?)")
        params.extend([tract_id, tract_id, tract_id])
        if not run_id:
            clauses.append(
                "o.run_id IN (SELECT tf.active_run_id FROM tiffs tf "
                "WHERE tf.tract_phase_pk=tp.tract_phase_pk AND tf.active_run_id IS NOT NULL)"
            )
    where = " AND ".join(clauses)
    conn = _connect(url)
    try:
        rows = conn.execute(
            "SELECT o.*, tp.tract_id, tp.region_id, tr.boundary_geom AS _boundary_geom, "
            "tr.effective_geom AS _effective_geom, tf.crs_epsg AS _crs_epsg, tf.crs_wkt AS _crs_wkt, "
            "r.task_type, r.parent_run_id "
            "FROM tree_observations o "
            "JOIN tract_phases tp ON tp.tract_phase_pk=o.tract_phase_pk "
            "JOIN tracts tr ON tr.tract_pk=tp.tract_pk "
            "JOIN runs r ON r.run_id=o.run_id "
            "LEFT JOIN tiffs tf ON tf.tiff_id=o.tiff_id AND tf.phase_id=o.phase_id "
            f"WHERE {where}",
            params,
        ).fetchall()
    finally:
        conn.close()
    obs = [_observation_row(dict(row)) for row in rows]
    obs = _filter_effective_observations(obs)
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
    phase_id: str | None = None,
    tiff_id: str | None = None,
    limit: int = 50,
) -> list[dict]:
    conn = _connect(url)
    try:
        bounded_limit = max(1, min(int(limit), 200))
        select_sql = (
            "SELECT r.*, "
            "(SELECT COUNT(*) FROM tree_observations o WHERE o.run_id=r.run_id) AS observation_count, "
            "tp.tract_id, tf.footprint_area_hm2, tf.area_hm2, tf.effective_area_hm2 "
            "FROM runs r "
            "LEFT JOIN tract_phases tp ON tp.tract_phase_pk = r.tract_phase_pk "
            "LEFT JOIN tiffs tf ON tf.tiff_id=r.tiff_id AND tf.phase_id=r.phase_id "
        )
        clauses: list[str] = []
        params: list[object] = []
        task_types = tuple(part.strip() for part in (task_type or "").split(",") if part.strip())
        if task_types:
            placeholders = ", ".join("?" for _ in task_types)
            clauses.append(f"r.task_type IN ({placeholders})")
            params.extend(task_types)
        if phase_id:
            clauses.append("r.phase_id=?")
            params.append(phase_id)
        if tiff_id:
            clauses.append("r.tiff_id=?")
            params.append(tiff_id)
        where = "WHERE " + " AND ".join(clauses) + " " if clauses else ""
        rows = conn.execute(
            select_sql + where + "ORDER BY r.started_at DESC LIMIT ?",
            (*params, bounded_limit),
        ).fetchall()
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


def list_tiffs(*, url: str | None = None) -> list[dict]:
    """返回全部 TIFF 资产明细，供地图总览与看板按影像维度聚合。"""
    conn = _connect(url)
    try:
        rows = conn.execute(
            "WITH run_aggregate AS ("
            " SELECT tiff_id, phase_id, COUNT(*) AS run_count, "
            " SUM(status='queued') AS queued_count, SUM(status='running') AS running_count, "
            " SUM(status='succeeded') AS succeeded_count, SUM(status='failed') AS failed_count, "
            " SUM(status='canceled') AS canceled_count "
            " FROM runs WHERE task_type IN ('infer', 'review') GROUP BY phase_id, tiff_id"
            ") "
            "SELECT tr.tract_pk, tr.region_id, tr.city, tr.county, tr.town, tr.tract_id, "
            "tr.boundary_geom, tr.boundary_geom_cent, tr.effective_geom, tr.effective_area_hm2, tr.effective_source, "
            "tp.tract_phase_pk, tp.phase_id, tp.area_hm2 AS tract_phase_area_hm2, tf.active_run_id, "
            "tf.tiff_id, tf.file_name, tf.path_versions, tf.tiff_type, tf.footprint_geom, tf.footprint_bbox, "
            "tf.center_geom, tf.crs_epsg, tf.crs_wkt, tf.geotransform, "
            "tf.pixel_width, tf.pixel_height, tf.gsd, tf.footprint_area_hm2, tf.area_hm2, tf.effective_area_hm2, tf.band_count, tf.dtype, tf.nodata, "
            "tf.inference_status, tf.effective_area_hm2 AS tiff_effective_area_hm2, tf.created_at, tf.updated_at, "
            "tf.active_run_id AS run_id, ar.status AS active_run_status, "
            "COALESCE(ar.ended_at, ar.started_at) AS detected_at, "
            "COALESCE(ra.run_count, 0) AS run_count, COALESCE(ra.queued_count, 0) AS queued_count, "
            "COALESCE(ra.running_count, 0) AS running_count, COALESCE(ra.succeeded_count, 0) AS succeeded_count, "
            "COALESCE(ra.failed_count, 0) AS failed_count, COALESCE(ra.canceled_count, 0) AS canceled_count, "
            "(SELECT COUNT(*) FROM tree_observations o WHERE o.run_id=tf.active_run_id) AS observation_count "
            "FROM tiffs tf "
            "JOIN tract_phases tp ON tp.tract_phase_pk=tf.tract_phase_pk "
            "JOIN tracts tr ON tr.tract_pk=tp.tract_pk "
            "LEFT JOIN runs ar ON ar.run_id=tf.active_run_id "
            "LEFT JOIN run_aggregate ra ON ra.tiff_id=tf.tiff_id AND ra.phase_id=tf.phase_id "
            "ORDER BY tr.tract_id, tp.phase_id DESC, tf.file_name"
        ).fetchall()
    finally:
        conn.close()

    out: list[dict] = []
    for row in rows:
        item = dict(row)
        if item.get("file_name"):
            item["file_name"] = Path(str(item["file_name"])).stem
        source_path = _latest_path(item.get("path_versions"))
        center = None
        if item.get("center_lng") is not None and item.get("center_lat") is not None:
            center = (float(item["center_lng"]), float(item["center_lat"]))
        if center is None:
            center = _parse_wkt_point(item.get("center_geom"))
        if center is None:
            center = _parse_wkt_polygon_centroid(item.get("footprint_geom"))
        if center is None:
            center = _parse_wkt_point(item.get("boundary_geom_cent"))
        count = int(item.get("observation_count") or 0)
        status_counts = {
            status_name: int(item.pop(f"{status_name}_count") or 0)
            for status_name in ("queued", "running", "succeeded", "failed", "canceled")
        }
        item["run_status_counts"] = {key: value for key, value in status_counts.items() if value}
        status = "已检测" if item.get("active_run_id") else "未检测"
        if not item.get("active_run_id") and (status_counts["queued"] or status_counts["running"]):
            status = "检测中"
        elif not item.get("active_run_id") and status_counts["failed"]:
            status = "检测失败"
        eff_hm2 = item.get("effective_area_hm2") or item.get("area_hm2") or item.get("footprint_area_hm2")
        item.update(
            {
                "source_path": source_path,
                "path_exists": bool(source_path and Path(source_path).expanduser().exists()),
                "center_lng": center[0] if center else None,
                "center_lat": center[1] if center else None,
                "geo_area": float(eff_hm2) * 10000.0 if eff_hm2 is not None else None,
                "status": status,
                "has_detection": status == "已检测",
            }
        )
        for geom_key in ("footprint_geom", "boundary_geom", "effective_geom"):
            if item.get(geom_key) and isinstance(item[geom_key], str):
                from shapely.wkt import loads as load_wkt
                from shapely.geometry import mapping
                try:
                    item[geom_key] = mapping(load_wkt(item[geom_key]))
                except Exception:
                    pass
        out.append(item)
    return out


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
            "SELECT tf.active_run_id FROM tiffs tf "
            "JOIN tract_phases tp ON tp.tract_phase_pk=tf.tract_phase_pk "
            "WHERE (tp.tract_id=? OR tp.tract_phase_pk=? OR tp.tract_pk=?) AND tf.active_run_id IS NOT NULL "
            "ORDER BY tp.phase_id DESC, tf.updated_at DESC LIMIT 1",
            (tract_id, tract_id, tract_id),
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
            "WHERE (tp.tract_id=? OR tp.tract_phase_pk=? OR tp.tract_pk=?) "
            "ORDER BY tp.phase_id DESC, tf.updated_at DESC LIMIT 1",
            (tract_id, tract_id, tract_id),
        ).fetchone()
    finally:
        conn.close()
    return _latest_path(row["path_versions"]) if row else None


def tiff_path(
    *,
    tract_id: str | None = None,
    phase_id: str | None = None,
    tiff_id: str | None = None,
    file_name: str | None = None,
    tract_phase_pk: str | None = None,
    url: str | None = None,
) -> str | None:
    clauses: list[str] = []
    params: list[str] = []
    if tract_id:
        clauses.append("tp.tract_id=?")
        params.append(tract_id)
    if phase_id:
        clauses.append("tp.phase_id=?")
        params.append(phase_id)
    if tract_phase_pk:
        clauses.append("tp.tract_phase_pk=?")
        params.append(tract_phase_pk)
    if tiff_id:
        clauses.append("tf.tiff_id=?")
        params.append(tiff_id)
    if file_name:
        clauses.append("(tf.file_name=? OR tf.file_name=? OR tf.file_name=? OR tf.file_name LIKE ?)")
        params.extend([file_name, Path(file_name).name, Path(file_name).stem, Path(file_name).stem + ".%"])
    if not clauses:
        return None
    conn = _connect(url)
    try:
        row = conn.execute(
            "SELECT tf.path_versions FROM tiffs tf "
            "JOIN tract_phases tp ON tp.tract_phase_pk=tf.tract_phase_pk "
            "WHERE " + " AND ".join(clauses) + " "
            "ORDER BY tp.phase_id DESC, tf.updated_at DESC LIMIT 1",
            params,
        ).fetchone()
    finally:
        conn.close()
    return _latest_path(row["path_versions"]) if row else None


def active_runs_for_tract_phase(tract_id: str, *, url: str | None = None) -> list[str]:
    """返回地块时相下每个 TIFF 资产已发布的 run_id 列表。"""
    conn = _connect(url)
    try:
        rows = conn.execute(
            "SELECT tf.active_run_id AS run_id FROM tiffs tf "
            "JOIN tract_phases tp ON tp.tract_phase_pk=tf.tract_phase_pk "
            "WHERE (tp.tract_id=? OR tp.tract_phase_pk=? OR tp.tract_pk=?) AND tf.active_run_id IS NOT NULL "
            "ORDER BY tf.created_at",
            (tract_id, tract_id, tract_id),
        ).fetchall()
        return [row["run_id"] for row in rows]
    finally:
        conn.close()
