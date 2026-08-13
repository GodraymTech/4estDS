"""Database write helpers for the tract -> phase -> TIFF -> tree model."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger as log

from ..geo.admin import (
    UNKNOWN_CITY,
    UNKNOWN_COUNTY,
    UNKNOWN_TOWN,
    normalize_city,
    normalize_county,
    region_id as format_region_id,
    split_region_id,
)
from .schema import init_db, resolve_db_path

_REGION_RE = re.compile(r"([\u4e00-\u9fffA-Za-z0-9]+)_([\u4e00-\u9fffA-Za-z0-9]+)")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_key() -> str:
    return datetime.now().strftime("%Y%m%d")


def _connect(url: str | None) -> sqlite3.Connection:
    init_db(url)
    from .schema import get_db_connection
    return get_db_connection(url)


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(raw: str | None, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _hash(text: str, n: int) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:n]


def _safe_pk(prefix: str, *parts: str) -> str:
    return f"{prefix}_{_hash(chr(0).join(parts), 12)}"


def _normalize_phase_id(value: str | None) -> str:
    s = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(s) == 6:
        return s + "01"
    if len(s) >= 8:
        return s[:8]
    return "00000000"


def _infer_region_id(*texts: str | None) -> str:
    for text in texts:
        if not text:
            continue
        match = _REGION_RE.search(str(text))
        if match:
            return format_region_id(match.group(1), match.group(2))
    return format_region_id(UNKNOWN_CITY, UNKNOWN_COUNTY)


def _resolve_admin(
    *,
    region_id: str | None,
    city: str | None,
    county: str | None,
    town: str | None,
    tract_id: str | None,
    image_path: str | None,
) -> tuple[str, str, str, str]:
    split_city, split_county = split_region_id(region_id) if region_id else (None, None)
    resolved_city = normalize_city(city or split_city or UNKNOWN_CITY)
    resolved_county = normalize_county(county or split_county or UNKNOWN_COUNTY)
    resolved_town = (town or UNKNOWN_TOWN).strip() or UNKNOWN_TOWN
    if resolved_county == UNKNOWN_COUNTY and region_id:
        _city, resolved_county = split_region_id(region_id)
    return format_region_id(resolved_city, resolved_county), resolved_city, resolved_county, resolved_town


def _path_version(path: str | None) -> str:
    return _dump({_today_key(): path}) if path else "{}"


def _merge_path_version(raw: str | None, path: str | None) -> str:
    data = _loads(raw, {})
    if path:
        data[_today_key()] = path
    return _dump(data)


def _merge_multisource(raw: str | None, source_type: str, path: str) -> str:
    data = _loads(raw, {})
    bucket = data.setdefault(source_type, {})
    bucket[_today_key()] = path
    return _dump(data)


def _wkt_polygon(coords: list[tuple[float, float]]) -> str:
    if not coords:
        return "POLYGON EMPTY"
    closed = coords + [coords[0]]
    return "POLYGON((" + ", ".join(f"{x} {y}" for x, y in closed) + "))"


def _wkt_point(x: float, y: float) -> str:
    return f"POINT({x} {y})"


def _tiff_type(image_path: str | None) -> str:
    if not image_path:
        return "invalid"
    try:
        from ..preprocess.cog import inspect_tiff_format

        return inspect_tiff_format(image_path)
    except Exception as exc:  # noqa: BLE001
        log.debug("TIFF 类型检测失败: path={} err={}", image_path, exc)
        return "invalid"


def _geo_area_from_wgs84(coords: list[tuple[float, float]]) -> float | None:
    if len(coords) < 3:
        return None
    try:
        from pyproj import Geod

        geod = Geod(ellps="WGS84")
        xs = [p[0] for p in coords]
        ys = [p[1] for p in coords]
        area, _ = geod.polygon_area_perimeter(xs, ys)
        return abs(float(area))
    except Exception as exc:  # noqa: BLE001
        log.debug("WGS84 footprint 面积计算失败: err={}", exc)
        return None


def _polygon_centroid(coords: list[tuple[float, float]]) -> tuple[float, float] | None:
    if not coords:
        return None
    if len(coords) < 3:
        x = sum(p[0] for p in coords) / len(coords)
        y = sum(p[1] for p in coords) / len(coords)
        return x, y
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
        x = sum(p[0] for p in coords) / len(coords)
        y = sum(p[1] for p in coords) / len(coords)
        return x, y
    area = signed_area * 0.5
    return cx / (6 * area), cy / (6 * area)


def _centroid_from_wkt_polygon(wkt: str | None) -> tuple[float, float] | None:
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
        return _polygon_centroid(coords)
    except (ValueError, IndexError):
        return None


def _compute_tiff_metadata(
    image_path: str | None,
    *,
    phase_id: str,
    tract_phase_pk: str,
    pixel_w: int | None = None,
    pixel_h: int | None = None,
    gsd: float | None = None,
    geo_area: float | None = None,
    area_unit: str | None = None,
    crs_epsg: int | None = None,
    crs_wkt: str | None = None,
) -> dict | None:
    if not image_path:
        return None

    path = Path(image_path)
    file_name = path.stem
    fallback_input = f"{phase_id}|{image_path}"
    meta: dict[str, Any] = {
        "tiff_id": _hash(fallback_input, 5),
        "phase_id": phase_id,
        "tract_phase_pk": tract_phase_pk,
        "file_name": file_name,
        "path_versions": _path_version(image_path),
        "multisource_path_versions": "{}",
        "tiff_type": _tiff_type(image_path),
        "footprint_geom": "POLYGON EMPTY",
        "footprint_bbox": None,
        "center_geom": None,
        "crs_epsg": crs_epsg,
        "crs_wkt": crs_wkt,
        "geotransform": None,
        "pixel_width": pixel_w,
        "pixel_height": pixel_h,
        "gsd": gsd,
        "footprint_area_hm2": round(geo_area / 10000.0, 4) if geo_area is not None else None,
        "area_hm2": round(geo_area / 10000.0, 4) if geo_area is not None else None,
        "band_count": None,
        "dtype": None,
        "nodata": None,
    }

    try:
        import rasterio
        from rasterio.warp import transform as warp_transform

        with rasterio.open(image_path) as src:
            width, height = int(src.width), int(src.height)
            corners_px = [(0, 0), (width, 0), (width, height), (0, height)]
            xs, ys = [], []
            for col, row in corners_px:
                x, y = src.transform * (col, row)
                xs.append(float(x))
                ys.append(float(y))
            if src.crs:
                lngs, lats = warp_transform(src.crs, "EPSG:4326", xs, ys)
                coords = [(round(float(x), 6), round(float(y), 6)) for x, y in zip(lngs, lats)]
            else:
                coords = [(round(float(x), 6), round(float(y), 6)) for x, y in zip(xs, ys)]
            normalized = ";".join(f"{round(x, 3):.3f},{round(y, 3):.3f}" for x, y in coords)
            minx, miny = min(x for x, _ in coords), min(y for _, y in coords)
            maxx, maxy = max(x for x, _ in coords), max(y for _, y in coords)
            center = _polygon_centroid(coords)
            pixel_area = abs(src.transform.a * src.transform.e - src.transform.b * src.transform.d)
            inferred_area = geo_area
            if inferred_area is None and pixel_area > 0:
                if src.crs and getattr(src.crs, "is_projected", False):
                    inferred_area = float(pixel_area * width * height)
                else:
                    inferred_area = _geo_area_from_wgs84(coords)
            
            footprint_hm2 = round(inferred_area / 10000.0, 4) if inferred_area is not None else None
            
            # 【方案A】：若带 Overview 或者是 COG，快速估算非 nodata 的有效面积
            estimated_effective_area_hm2 = footprint_hm2
            try:
                if len(src.overviews(1)) > 0:
                    factors = src.overviews(1)
                    max_level = len(factors) - 1
                    decim = factors[max_level]
                    ov_h = int(src.height // decim)
                    ov_w = int(src.width // decim)
                    from rasterio.enums import Resampling
                    data = src.read(1, out_shape=(ov_h, ov_w), resampling=Resampling.nearest)
                    nodata_val = src.nodata
                    import numpy as np
                    if nodata_val is not None:
                        if np.isnan(nodata_val):
                            valid_pixels = np.count_nonzero(~np.isnan(data))
                        else:
                            valid_pixels = np.count_nonzero(data != nodata_val)
                    else:
                        valid_pixels = data.size
                    
                    if data.size > 0 and inferred_area:
                        valid_ratio = float(valid_pixels) / data.size
                        estimated_effective_area_hm2 = round((inferred_area * valid_ratio) / 10000.0, 4)
                        if estimated_effective_area_hm2 <= 0:
                            estimated_effective_area_hm2 = footprint_hm2
            except Exception as exc:
                log.debug("从 Overview 估算有效面积失败: {}", exc)

            meta.update(
                {
                    "tiff_id": _hash(f"{phase_id}|{normalized}|{path.resolve()}", 5),
                    "footprint_geom": _wkt_polygon(coords),
                    "footprint_bbox": _dump([minx, miny, maxx, maxy]),
                    "center_geom": _wkt_point(*center) if center else None,
                    "crs_epsg": src.crs.to_epsg() if src.crs and hasattr(src.crs, "to_epsg") else crs_epsg,
                    "crs_wkt": src.crs.to_wkt() if src.crs and hasattr(src.crs, "to_wkt") else crs_wkt,
                    "geotransform": _dump(tuple(src.transform)),
                    "pixel_width": width,
                    "pixel_height": height,
                    "gsd": gsd if gsd is not None else (float(pixel_area ** 0.5) if pixel_area > 0 and src.crs and getattr(src.crs, "is_projected", False) else None),
                    "footprint_area_hm2": footprint_hm2,
                    "area_hm2": estimated_effective_area_hm2,
                    "effective_area_hm2": estimated_effective_area_hm2,
                    "band_count": int(src.count),
                    "dtype": str(src.dtypes[0]) if src.dtypes else None,
                    "nodata": src.nodata,
                }
            )
    except Exception as exc:  # noqa: BLE001
        log.debug("TIFF 元数据读取失败，使用降级身份: path={} err={}", image_path, exc)

    return meta


def _ensure_run_exists(conn: sqlite3.Connection, run_id: str, task_type: str = "infer") -> None:
    now = _now()
    conn.execute(
        "INSERT INTO runs (run_id, task_type, status, started_at, created_at) "
        "VALUES (?, ?, 'running', ?, ?) "
        "ON CONFLICT(run_id) DO NOTHING",
        (run_id, task_type, now, now),
    )


def start_run_log(
    run_id: str,
    task_type: str,
    *,
    url: str | None = None,
    model_arch: str | None = None,
    input_path: str | None = None,
    params: dict | None = None,
    tag: str | None = None,
    parent_run_id: str | None = None,
    slice_size: int | None = None,
) -> str:
    """插入一条 running 状态的 runs 记录。返回 run_id。"""
    now = _now()
    conn = _connect(url)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO runs "
            "(run_id, parent_run_id, tag, task_type, model_arch, status, started_at, created_at, "
            " input_path, input_json, params_json, slice_size) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                parent_run_id,
                tag,
                task_type,
                model_arch,
                "running",
                now,
                now,
                input_path,
                _dump({"input_path": input_path}) if input_path else None,
                _dump(params or {}),
                slice_size,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    log.info("写入「runs」表: run_id={} task={} arch={} input={}", run_id, task_type, model_arch, input_path)
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
    """更新 runs 为终态。"""
    normalized_status = "canceled" if status == "cancelled" else status
    conn = _connect(url)
    try:
        _ensure_run_exists(conn, run_id)
        conn.execute(
            "UPDATE runs SET status=?, ended_at=?, duration_s=?, metrics_json=?, error=? WHERE run_id=?",
            (normalized_status, _now(), duration_s, _dump(metrics or {}), error, run_id),
        )
        conn.commit()
    finally:
        conn.close()
    if normalized_status != "succeeded":
        log.error("runs 终态: run_id={} status={} error={}", run_id, normalized_status, error)
    else:
        log.info("「runs」表更新终态: run_id={} status={} 耗时={}s", run_id, normalized_status, f"{duration_s:.2f}" if duration_s is not None else "?")


def update_tiles_dir(run_id: str, tiles_dir, *, url: str | None = None) -> None:
    """切片落盘成功后，将目录绝对路径写入 runs.tiles_dir。"""
    conn = _connect(url)
    try:
        _ensure_run_exists(conn, run_id)
        conn.execute("UPDATE runs SET tiles_dir=? WHERE run_id=?", (str(Path(tiles_dir).resolve()), run_id))
        conn.commit()
    finally:
        conn.close()
    log.debug("tiles_dir 已记录至 runs: run_id={} dir={}", run_id, tiles_dir)


def ensure_tract(
    phase_id: str,
    tract_id: str,
    *,
    url: str | None = None,
    region_id: str | None = None,
    city: str | None = None,
    county: str | None = None,
    town: str | None = None,
    pixel_w: int | None = None,
    pixel_h: int | None = None,
    gsd: float | None = None,
    geo_area: float | None = None,
    area_unit: str | None = None,
    crs_epsg: int | None = None,
    crs_wkt: str | None = None,
    image_path: str | None = None,
    boundary_geom: str | None = None,
) -> str:
    """幂等获取/创建地块、地块时相和可选 TIFF，返回用户可见 tract_id。"""
    phase_id = _normalize_phase_id(phase_id)
    resolved_tract_id = (tract_id or (Path(image_path).stem if image_path else "")).strip()
    if not resolved_tract_id:
        tract_id = f"tract_{uuid.uuid4().hex[:5]}"
    else:
        tract_id = resolved_tract_id
    resolved_region_id, city, county, town = _resolve_admin(
        region_id=region_id,
        city=city,
        county=county,
        town=town,
        tract_id=tract_id,
        image_path=image_path,
    )
    tract_pk = _safe_pk("tract", resolved_region_id, tract_id)
    now = _now()

    conn = _connect(url)
    try:
        existing_tract = conn.execute(
            "SELECT tract_pk FROM tracts WHERE region_id=? AND tract_id=? LIMIT 1",
            (resolved_region_id, tract_id),
        ).fetchone()
        if not existing_tract and (city == UNKNOWN_CITY or county == UNKNOWN_COUNTY):
            existing_tract = conn.execute(
                "SELECT tr.tract_pk, tr.region_id, tr.city, tr.county, tr.town "
                "FROM tracts tr "
                "JOIN tract_phases tp ON tp.tract_pk=tr.tract_pk "
                "WHERE tr.tract_id=? AND tp.phase_id=? "
                "ORDER BY CASE WHEN tr.city<>? AND tr.county<>? THEN 0 ELSE 1 END, tr.updated_at DESC "
                "LIMIT 1",
                (tract_id, phase_id, UNKNOWN_CITY, UNKNOWN_COUNTY),
            ).fetchone()
        if not existing_tract and (city == UNKNOWN_CITY or county == UNKNOWN_COUNTY):
            existing_tract = conn.execute(
                "SELECT tract_pk, region_id, city, county, town FROM tracts "
                "WHERE tract_id=? "
                "ORDER BY CASE WHEN city<>? AND county<>? THEN 0 ELSE 1 END, updated_at DESC "
                "LIMIT 1",
                (tract_id, UNKNOWN_CITY, UNKNOWN_COUNTY),
            ).fetchone()
        if existing_tract:
            tract_pk = existing_tract["tract_pk"]
            if "region_id" in existing_tract.keys():
                resolved_region_id = existing_tract["region_id"] or resolved_region_id
                city = existing_tract["city"] or city
                county = existing_tract["county"] or county
                town = existing_tract["town"] or town
        tract_phase_pk = _safe_pk("phase", tract_pk, phase_id)
        conn.execute(
            "INSERT INTO tracts "
            "(tract_pk, region_id, city, county, town, tract_id, boundary_geom, boundary_geom_cent, "
            "effective_geom, effective_area_hm2, effective_source, coverage_status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(tract_pk) DO UPDATE SET region_id=excluded.region_id, city=excluded.city, county=excluded.county, "
            "town=excluded.town, updated_at=excluded.updated_at",
            (
                tract_pk,
                resolved_region_id,
                city,
                county,
                town,
                tract_id,
                None,
                None,
                None,
                None,
                "default",
                "none",
                now,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO tract_phases "
            "(tract_phase_pk, tract_pk, region_id, tract_id, phase_id, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(tract_pk, phase_id) DO UPDATE SET region_id=excluded.region_id, "
            "tract_id=excluded.tract_id, updated_at=excluded.updated_at",
            (
                tract_phase_pk,
                tract_pk,
                resolved_region_id,
                tract_id,
                phase_id,
                now,
            ),
        )

        tiff_meta = _compute_tiff_metadata(
            image_path,
            phase_id=phase_id,
            tract_phase_pk=tract_phase_pk,
            pixel_w=pixel_w,
            pixel_h=pixel_h,
            gsd=gsd,
            geo_area=geo_area,
            area_unit=area_unit,
            crs_epsg=crs_epsg,
            crs_wkt=crs_wkt,
        )
        if tiff_meta:
            existing = conn.execute(
                "SELECT path_versions, multisource_path_versions FROM tiffs WHERE tiff_id=? AND phase_id=?",
                (tiff_meta["tiff_id"], phase_id),
            ).fetchone()
            if existing:
                tiff_meta["path_versions"] = _merge_path_version(existing["path_versions"], image_path)
                tiff_meta["multisource_path_versions"] = existing["multisource_path_versions"] or "{}"
            conn.execute(
                "INSERT INTO tiffs "
                "(tiff_id, phase_id, tract_phase_pk, file_name, path_versions, multisource_path_versions, "
                " tiff_type, footprint_geom, footprint_bbox, center_geom, crs_epsg, crs_wkt, geotransform, "
                " pixel_width, pixel_height, gsd, footprint_area_hm2, area_hm2, effective_area_hm2, "
                " band_count, dtype, nodata, inference_status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(tiff_id, phase_id) DO UPDATE SET "
                " tract_phase_pk=excluded.tract_phase_pk, file_name=excluded.file_name, path_versions=excluded.path_versions, "
                " multisource_path_versions=excluded.multisource_path_versions, tiff_type=excluded.tiff_type, "
                " footprint_geom=excluded.footprint_geom, footprint_bbox=excluded.footprint_bbox, "
                " center_geom=excluded.center_geom, crs_epsg=excluded.crs_epsg, crs_wkt=excluded.crs_wkt, "
                " geotransform=excluded.geotransform, pixel_width=excluded.pixel_width, pixel_height=excluded.pixel_height, "
                " gsd=excluded.gsd, footprint_area_hm2=excluded.footprint_area_hm2, area_hm2=excluded.area_hm2, "
                " effective_area_hm2=COALESCE(tiffs.effective_area_hm2, excluded.effective_area_hm2), "
                " band_count=excluded.band_count, dtype=excluded.dtype, nodata=excluded.nodata, "
                " updated_at=excluded.updated_at",
                (
                    tiff_meta["tiff_id"],
                    phase_id,
                    tract_phase_pk,
                    tiff_meta["file_name"],
                    tiff_meta["path_versions"],
                    tiff_meta["multisource_path_versions"],
                    tiff_meta["tiff_type"],
                    tiff_meta["footprint_geom"],
                    tiff_meta["footprint_bbox"],
                    tiff_meta["center_geom"],
                    tiff_meta["crs_epsg"],
                    tiff_meta["crs_wkt"],
                    tiff_meta["geotransform"],
                    tiff_meta["pixel_width"],
                    tiff_meta["pixel_height"],
                    tiff_meta["gsd"],
                    tiff_meta.get("footprint_area_hm2"),
                    tiff_meta.get("area_hm2"),
                    tiff_meta.get("effective_area_hm2"),
                    tiff_meta["band_count"],
                    tiff_meta["dtype"],
                    tiff_meta["nodata"],
                    "pending",
                    now,
                    now,
                ),
            )
            update_tract_geom_from_tiffs(conn, tract_pk)

        conn.commit()
    finally:
        conn.close()
    return tract_id


def _resolve_context(
    conn: sqlite3.Connection,
    tract_id: str,
    *,
    phase_id: str | None = None,
    image_path: str | None = None,
) -> tuple[str, str, str | None]:
    normalized_phase = _normalize_phase_id(phase_id)
    row = None
    if normalized_phase != "00000000":
        row = conn.execute(
            "SELECT tract_phase_pk, phase_id FROM tract_phases WHERE tract_id=? AND phase_id=? ORDER BY updated_at DESC LIMIT 1",
            (tract_id, normalized_phase),
        ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT tract_phase_pk, phase_id FROM tract_phases WHERE tract_id=? ORDER BY phase_id DESC LIMIT 1",
            (tract_id,),
        ).fetchone()
    if row is None:
        fallback_phase = normalized_phase if normalized_phase != "00000000" else _today_key()
        ensure_tract(fallback_phase, tract_id, image_path=image_path)
        row = conn.execute(
            "SELECT tract_phase_pk, phase_id FROM tract_phases WHERE tract_id=? AND phase_id=?",
            (tract_id, fallback_phase),
        ).fetchone()
    if row is None:
        raise ValueError(f"无法解析地块时相: tract_id={tract_id} phase_id={phase_id}")
    tiff_row = None
    if image_path:
        image_name = Path(image_path).name
        resolved_image_path = str(Path(image_path).expanduser().resolve())
        tiff_row = conn.execute(
            "SELECT tiff_id FROM tiffs "
            "WHERE tract_phase_pk=? AND (path_versions LIKE ? OR path_versions LIKE ? OR file_name=? OR file_name=?) "
            "ORDER BY updated_at DESC LIMIT 1",
            (
                row["tract_phase_pk"],
                f"%{image_path}%",
                f"%{resolved_image_path}%",
                image_name,
                Path(image_name).stem,
            ),
        ).fetchone()
    if tiff_row is None:
        tiff_row = conn.execute(
            "SELECT tiff_id FROM tiffs WHERE tract_phase_pk=? ORDER BY created_at DESC LIMIT 1",
            (row["tract_phase_pk"],),
        ).fetchone()
    return row["tract_phase_pk"], row["phase_id"], (tiff_row["tiff_id"] if tiff_row else None)


def write_observations(
    tract_id: str,
    run_id: str,
    detections,
    *,
    url: str | None = None,
    slice_size: int | None = None,
    image_path: str | None = None,
    transform=None,
    crs=None,
    phase_id: str | None = None,
) -> int:
    """将一次 run 的全图检测写入 tree_observations。返回写入条数。"""
    from ..geo import resolve_geo

    geo = None
    try:
        geo = resolve_geo(image_path, transform=transform, crs=crs)
    except Exception as geo_err:  # noqa: BLE001
        log.warning("解析地理元数据失败: {}", geo_err)

    gsd = geo.gsd_m() if geo else None
    pixel_area_val = geo.pixel_area_m2() if geo else None
    now = _now()

    conn = _connect(url)
    n = 0
    try:
        tract_phase_pk, resolved_phase_id, tiff_id = _resolve_context(
            conn, tract_id, phase_id=phase_id, image_path=image_path
        )
        _ensure_run_exists(conn, run_id)
        conn.execute(
            "UPDATE runs SET tract_phase_pk=?, tiff_id=COALESCE(tiff_id, ?), phase_id=?, slice_size=COALESCE(slice_size, ?) WHERE run_id=?",
            (tract_phase_pk, tiff_id, resolved_phase_id, slice_size, run_id),
        )

        for d in detections:
            observation_id = f"obs_{uuid.uuid4().hex[:12]}"
            cx, cy = d.center
            extra = getattr(d, "extra", None) or {}
            height = extra.get("height")
            height_source = extra.get("height_source")
            box_px_sub = extra.get("box_px_sub")
            source_subimage_path = extra.get("source_subimage_path")

            crown_area_px = extra.get("crown_area_px")
            if crown_area_px is None:
                crown_area_px = extra.get("crown_area_px_est")
            if crown_area_px is None:
                crown_area_px = extra.get("crown_area_px_real")
            if crown_area_px is None:
                crown_area_px = float(d.width * d.height)
            crown_area_geo_est = extra.get("crown_area_geo_est")
            crown_area_geo_real = extra.get("crown_area_geo_real")
            crown_volume_geo_est = extra.get("volume_est")
            crown_volume_geo_real = extra.get("volume_real")

            center_geom = None
            box_geo = None
            crown_geom = None
            crown_width_geo = None
            crown_height_geo = None
            fallback_area_geo = None

            if geo:
                try:
                    cx_geo, cy_geo = geo.transform.pixel_to_world(cx, cy)
                    center_geom = f"POINT({cx_geo} {cy_geo})"
                    x1_geo, y1_geo = geo.transform.pixel_to_world(d.x1, d.y1)
                    x2_geo, y2_geo = geo.transform.pixel_to_world(d.x2, d.y2)
                    box_geo = _dump([x1_geo, y1_geo, x2_geo, y2_geo])
                    crown_geom = (
                        f"POLYGON(({x1_geo} {y1_geo}, {x2_geo} {y1_geo}, "
                        f"{x2_geo} {y2_geo}, {x1_geo} {y2_geo}, {x1_geo} {y1_geo}))"
                    )
                    if gsd:
                        crown_width_geo = d.width * gsd
                        crown_height_geo = d.height * gsd
                        fallback_area_geo = (
                            (d.width * d.height) * pixel_area_val
                            if pixel_area_val
                            else (d.width * d.height) * (gsd * gsd)
                        )
                except Exception as exc:  # noqa: BLE001
                    log.warning("单木像素坐标转地理坐标失败: {}", exc)

            if crown_area_px is None:
                crown_area_px = float(d.width * d.height)
            if crown_area_geo_est is None:
                crown_area_geo_est = fallback_area_geo if fallback_area_geo is not None else (float(d.width * d.height * (gsd * gsd)) if gsd else 0.0)
            if crown_area_geo_real is None:
                crown_area_geo_real = crown_area_geo_est

            conn.execute(
                "INSERT INTO tree_observations "
                "(observation_id, run_id, tract_phase_pk, tiff_id, phase_id, species, confidence, "
                " center_geom, crown_geom, box_px, box_px_sub, box_geo, crown_width_px, crown_height_px, "
                " crown_width_geo, crown_height_geo, crown_area_px, crown_area_geo_est, crown_area_geo_real, "
                " height, height_source, crown_volume_geo_est, crown_volume_geo_real, source_subimage_path, "
                " slice_size, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    observation_id,
                    run_id,
                    tract_phase_pk,
                    tiff_id,
                    resolved_phase_id,
                    d.label,
                    d.score,
                    center_geom,
                    crown_geom,
                    _dump([d.x1, d.y1, d.x2, d.y2]),
                    _dump(box_px_sub) if box_px_sub else None,
                    box_geo,
                    d.width,
                    d.height,
                    crown_width_geo,
                    crown_height_geo,
                    crown_area_px,
                    crown_area_geo_est,
                    crown_area_geo_real,
                    height,
                    height_source,
                    crown_volume_geo_est,
                    crown_volume_geo_real,
                    source_subimage_path,
                    slice_size,
                    now,
                ),
            )
            n += 1

        if tiff_id:
            conn.execute(
                "UPDATE tiffs SET inference_status='inferred', updated_at=? WHERE tiff_id=? AND phase_id=?",
                (now, tiff_id, resolved_phase_id),
            )
        conn.commit()
    finally:
        conn.close()
    log.info("写「tree_observations」表: 本轮最终单木 {} 株 -> run_id={} slice_size={}", n, run_id, slice_size)
    return n


def count_observations(run_id: str, *, url: str | None = None) -> int:
    conn = _connect(url)
    try:
        row = conn.execute("SELECT COUNT(*) FROM tree_observations WHERE run_id=?", (run_id,)).fetchone()
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
    phase_id: str | None = None,
) -> str:
    """登记 TIFF 的一个 multisource 文件路径版本。"""
    conn = _connect(url)
    try:
        tract_phase_pk, resolved_phase_id, tiff_id = _resolve_context(conn, tract_id, phase_id=phase_id)
        if not tiff_id:
            raise ValueError(f"地块时相尚未登记 TIFF，无法登记 multisource: {tract_id} {resolved_phase_id}")
        row = conn.execute(
            "SELECT multisource_path_versions FROM tiffs WHERE tiff_id=? AND phase_id=?",
            (tiff_id, resolved_phase_id),
        ).fetchone()
        merged = _merge_multisource(row["multisource_path_versions"] if row else None, source_type, path)
        conn.execute(
            "UPDATE tiffs SET multisource_path_versions=?, updated_at=? WHERE tiff_id=? AND phase_id=?",
            (merged, _now(), tiff_id, resolved_phase_id),
        )
        conn.commit()
        source_id = f"{tiff_id}_{resolved_phase_id}_{source_type}"
    finally:
        conn.close()
    log.info("multisource 登记: tract={} phase={} type={} path={}", tract_id, phase_id, source_type, path)
    return source_id


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


def promote_run(run_id: str, *, url: str | None = None) -> None:
    """原子发布一个成功 run，设置其 TIFF 的正式结果事实源。"""
    conn = _connect(url)
    conn.row_factory = sqlite3.Row
    try:
        run_row = conn.execute(
            "SELECT status, phase_id, tiff_id FROM runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if not run_row:
            raise ValueError(f"推理任务 {run_id} 不存在。")
        if run_row["status"] != "succeeded":
            raise ValueError(f"推理任务 {run_id} 状态为 '{run_row['status']}'，只有成功的任务才能发布。")

        phase_id = run_row["phase_id"]
        tiff_id = run_row["tiff_id"]
        if not phase_id or not tiff_id:
            raise ValueError(f"无法确定推理任务 {run_id} 关联的 TIFF。")

        now = _now()
        updated = conn.execute(
            "UPDATE tiffs SET active_run_id=?, updated_at=? WHERE phase_id=? AND tiff_id=?",
            (run_id, now, phase_id, tiff_id),
        )
        if updated.rowcount != 1:
            raise ValueError(f"推理任务 {run_id} 关联的 TIFF 不存在: {phase_id}/{tiff_id}")
        conn.commit()
        log.info("推理任务 {} 已发布为 TIFF {}/{} 的正式版本。", run_id, phase_id, tiff_id)
    finally:
        conn.close()


def persist_individuals(individuals, *, url: str | None = None) -> int:
    """写入跨时相个体 tree_individuals，并按 observation_id 回填观测。"""
    conn = _connect(url)
    n = 0
    linked = 0
    now = _now()
    try:
        for ind in individuals:
            status = ind.get("status") or "alive"
            if status == "dead":
                status = "removed"
            if status not in {"alive", "missing", "removed", "unknown"}:
                status = "unknown"
            conn.execute(
                "INSERT INTO tree_individuals "
                "(individual_id, first_seen_phase_id, last_seen_phase_id, global_status, tracking_confidence, growth_json, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(individual_id) DO UPDATE SET "
                " first_seen_phase_id=excluded.first_seen_phase_id, last_seen_phase_id=excluded.last_seen_phase_id, "
                " global_status=excluded.global_status, tracking_confidence=excluded.tracking_confidence, "
                " growth_json=excluded.growth_json, updated_at=excluded.updated_at",
                (
                    ind["individual_id"],
                    ind.get("first_seen"),
                    ind.get("last_seen"),
                    status,
                    ind.get("tracking_confidence"),
                    ind.get("growth_json"),
                    now,
                    now,
                ),
            )
            n += 1
            for _time, obs_key in (ind.get("members") or {}).items():
                cur = conn.execute(
                    "UPDATE tree_observations SET individual_id=? WHERE observation_id=?",
                    (ind["individual_id"], obs_key),
                )
                if cur.rowcount and cur.rowcount > 0:
                    linked += cur.rowcount
        conn.commit()
    finally:
        conn.close()
    log.info("个体持久化: {} 个体, 回填观测 {} 条", n, linked)
    return n


def update_tract_geom_from_tiffs(conn: sqlite3.Connection, tract_pk: str) -> None:
    """重新计算并更新该地块下全量 TIFF 的合并外接正矩形与有效区域。"""
    import json
    row = conn.execute(
        "SELECT effective_source FROM tracts WHERE tract_pk=?", (tract_pk,)
    ).fetchone()
    if not row:
        return

    effective_source = (row["effective_source"] if hasattr(row, "keys") else row[0]) or "default"

    # 获取该地块下所有的 TIFF 资产 footprint_bbox
    # bbox 存储格式为 JSON 字符串: [minx, miny, maxx, maxy]
    bbox_rows = conn.execute(
        "SELECT tf.footprint_bbox FROM tiffs tf "
        "JOIN tract_phases tp ON tp.tract_phase_pk = tf.tract_phase_pk "
        "WHERE tp.tract_pk=?",
        (tract_pk,),
    ).fetchall()

    now = _now()
    if not bbox_rows:
        if effective_source == "default":
            conn.execute(
                "UPDATE tracts SET boundary_geom=NULL, boundary_geom_cent=NULL, "
                "effective_geom=NULL, effective_area_hm2=NULL, updated_at=? WHERE tract_pk=?",
                (now, tract_pk),
            )
        else:
            conn.execute(
                "UPDATE tracts SET boundary_geom=NULL, boundary_geom_cent=NULL, updated_at=? WHERE tract_pk=?",
                (now, tract_pk),
            )
        return

    # 解析所有 bbox 并合并
    min_lng, min_lat = float("inf"), float("inf")
    max_lng, max_lat = float("-inf"), float("-inf")
    valid_bbox_found = False

    for r in bbox_rows:
        bbox_str = r["footprint_bbox"] if hasattr(r, "keys") else r[0]
        if not bbox_str:
            continue
        try:
            bbox = json.loads(bbox_str)
            if isinstance(bbox, list) and len(bbox) == 4:
                min_lng = min(min_lng, float(bbox[0]))
                min_lat = min(min_lat, float(bbox[1]))
                max_lng = max(max_lng, float(bbox[2]))
                max_lat = max(max_lat, float(bbox[3]))
                valid_bbox_found = True
        except (TypeError, ValueError):
            continue

    if not valid_bbox_found:
        if effective_source == "default":
            conn.execute(
                "UPDATE tracts SET boundary_geom=NULL, boundary_geom_cent=NULL, "
                "effective_geom=NULL, effective_area_hm2=NULL, updated_at=? WHERE tract_pk=?",
                (now, tract_pk),
            )
        else:
            conn.execute(
                "UPDATE tracts SET boundary_geom=NULL, boundary_geom_cent=NULL, updated_at=? WHERE tract_pk=?",
                (now, tract_pk),
            )
        return

    # 构造外接正矩形 WKT 多边形
    coords = [
        (min_lng, min_lat),
        (max_lng, min_lat),
        (max_lng, max_lat),
        (min_lng, max_lat),
        (min_lng, min_lat)
    ]
    boundary_geom = _wkt_polygon(coords)
    center = ((min_lng + max_lng) / 2.0, (min_lat + max_lat) / 2.0)
    boundary_geom_cent = _wkt_point(*center)

    conn.execute(
        "UPDATE tract_phases SET area_hm2 = ("
        "  SELECT COALESCE(SUM(area_hm2), 0.0) FROM tiffs WHERE tract_phase_pk = tract_phases.tract_phase_pk"
        ") WHERE tract_pk=?",
        (tract_pk,),
    )
    if effective_source == "default":
        effective_geom = boundary_geom
        conn.execute(
            "UPDATE tiffs SET effective_area_hm2 = COALESCE(area_hm2, footprint_area_hm2) "
            "WHERE tract_phase_pk IN (SELECT tract_phase_pk FROM tract_phases WHERE tract_pk=?)",
            (tract_pk,),
        )
        row_phase = conn.execute(
            "SELECT tp.phase_id, COUNT(tf.tiff_id) as cnt FROM tract_phases tp "
            "JOIN tiffs tf ON tf.tract_phase_pk = tp.tract_phase_pk "
            "WHERE tp.tract_pk=? GROUP BY tp.phase_id ORDER BY cnt DESC, tp.phase_id DESC LIMIT 1",
            (tract_pk,),
        ).fetchone()
        best_phase = (row_phase["phase_id"] if hasattr(row_phase, "keys") else row_phase[0]) if row_phase else None
        if best_phase:
            sum_row = conn.execute(
                "SELECT SUM(tf.effective_area_hm2) as total FROM tiffs tf "
                "JOIN tract_phases tp ON tp.tract_phase_pk = tf.tract_phase_pk "
                "WHERE tp.tract_pk=? AND tp.phase_id=?",
                (tract_pk, best_phase),
            ).fetchone()
            effective_area_hm2 = (sum_row["total"] if hasattr(sum_row, "keys") else sum_row[0]) if sum_row else None
        else:
            effective_area_hm2 = None

        conn.execute(
            "UPDATE tracts SET boundary_geom=?, boundary_geom_cent=?, "
            "effective_geom=?, effective_area_hm2=?, updated_at=? WHERE tract_pk=?",
            (boundary_geom, boundary_geom_cent, effective_geom, effective_area_hm2, now, tract_pk),
        )
    else:
        conn.execute(
            "UPDATE tracts SET boundary_geom=?, boundary_geom_cent=?, updated_at=? WHERE tract_pk=?",
            (boundary_geom, boundary_geom_cent, now, tract_pk),
        )
