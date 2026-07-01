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

from loguru import logger as log
from .schema import init_db, resolve_db_path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(url: str | None) -> sqlite3.Connection:
    db_path = resolve_db_path(url)
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
        "写入「run_log」表: run_id={} task={} arch={} input={}",
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
            log.error("run_log 终态: run_id={} status={} error={}", run_id, status, error)
        else:
            log.info(
                "「run_log」表更新终态: run_id={} status={} 耗时={}s",
                run_id, status, f"{duration_s:.2f}" if duration_s is not None else "?",
            )
        conn.commit()
    finally:
        conn.close()


def update_tiles_dir(run_id: str, tiles_dir, *, url: str | None = None) -> None:
    """切片落盘成功后，将目录绝对路径写入 run_logs.tiles_dir。"""
    from pathlib import Path as _Path
    conn = _connect(url)
    try:
        conn.execute(
            "UPDATE run_logs SET tiles_dir=? WHERE run_id=?",
            (str(_Path(tiles_dir).resolve()), run_id),
        )
        conn.commit()
    finally:
        conn.close()
    log.debug("tiles_dir 已记录至 run_logs: run_id={} dir={}", run_id, tiles_dir)


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
    crs_epsg: int | None = None,
    crs_wkt: str | None = None,
) -> str:
    """按 (acquisition_time, location) 幂等获取/创建地块,返回 tract_id。"""
    conn = _connect(url)
    try:
        row = conn.execute(
            "SELECT tract_id FROM tracts WHERE acquisition_time=? AND location=?",
            (acquisition_time, location),
        ).fetchone()
        if row:
            if crs_epsg is not None or crs_wkt is not None:
                conn.execute(
                    "UPDATE tracts SET "
                    "crs_epsg=COALESCE(crs_epsg, ?), "
                    "crs_wkt=COALESCE(crs_wkt, ?) "
                    "WHERE tract_id=?",
                    (crs_epsg, crs_wkt, row[0]),
                )
                conn.commit()
            return row[0]
        name_part = ""
        if name:
            clean_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name)
            name_part = f"{clean_name[:20]}_"
        tract_id = f"tract_{name_part}{acquisition_time}_{uuid.uuid4().hex[:5]}"
        conn.execute(
            "INSERT INTO tracts "
            "(tract_id, name, acquisition_time, location, pixel_w, pixel_h, gsd, "
            " geo_area, area_unit, crs_epsg, crs_wkt, status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (tract_id, name, acquisition_time, location,
             pixel_w, pixel_h, gsd, geo_area, area_unit, crs_epsg, crs_wkt, "registered"),
        )
        if geo_area:
            log.info(
                "原图地块信息注入「tracts」表: tract_id={}", tract_id )
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
    image_path: str | None = None,
    transform=None,
    crs=None,
) -> int:
    """将一次 run 的全图检测(已 WBF 去重)写入 tree_observations。返回写入条数。

    detections: 可迭代 of Detection(含 x1,y1,x2,y2,score,label,center)。
    """
    from ..geo import resolve_geo
    geo = None
    try:
        geo = resolve_geo(image_path, transform=transform, crs=crs)
    except Exception as geo_err:
        log.warning(f"解析地理元数据失败: {geo_err}")
        
    gsd = geo.gsd_m() if geo else None
    pixel_area_val = geo.pixel_area_m2() if geo else None

    conn = _connect(url)
    n = 0
    try:
        for d in detections:
            obs_id = f"obs_{uuid.uuid4().hex[:12]}"
            cx, cy = d.center
            extra = getattr(d, "extra", None) or {}
            height = extra.get("height")
            height_source = extra.get("height_source")
            crown_volume_geo = extra.get("volume")
            box_px_sub = extra.get("box_px_sub")
            source_subimage_path = extra.get("source_subimage_path")
            
            crown_area_px_est = extra.get("crown_area_px_est")
            crown_area_px_real = extra.get("crown_area_px_real")
            crown_area_geo_est = extra.get("crown_area_geo_est")
            crown_area_geo_real = extra.get("crown_area_geo_real")
            crown_volume_geo_est = extra.get("volume_est")
            crown_volume_geo_real = extra.get("volume_real")

            # 计算地理空间字段
            center_geo = None
            box_geo = None
            geom_crown = None
            crown_w_geo = None
            crown_h_geo = None
            crown_area_geo = None
            
            if geo:
                try:
                    cx_geo, cy_geo = geo.transform.pixel_to_world(cx, cy)
                    center_geo = f"POINT({cx_geo} {cy_geo})"
                    
                    x1_geo, y1_geo = geo.transform.pixel_to_world(d.x1, d.y1)
                    x2_geo, y2_geo = geo.transform.pixel_to_world(d.x2, d.y2)
                    box_geo = json.dumps([x1_geo, y1_geo, x2_geo, y2_geo])
                    geom_crown = f"POLYGON(({x1_geo} {y1_geo}, {x2_geo} {y1_geo}, {x2_geo} {y2_geo}, {x1_geo} {y2_geo}, {x1_geo} {y1_geo}))"
                    
                    if gsd:
                        crown_w_geo = d.width * gsd
                        crown_h_geo = d.height * gsd
                        if pixel_area_val:
                            crown_area_geo = (d.width * d.height) * pixel_area_val
                        else:
                            crown_area_geo = (d.width * d.height) * (gsd * gsd)
                except Exception as e:
                    log.warning(f"单木像素坐标转地理坐标失败: {e}")

            # 填充没有多源数据时的回退计算值
            if crown_area_px_est is None:
                crown_area_px_est = float(d.width * d.height)
            if crown_area_px_real is None:
                crown_area_px_real = crown_area_px_est
            if crown_area_geo_est is None:
                crown_area_geo_est = crown_area_geo if crown_area_geo is not None else (float(d.width * d.height * (gsd * gsd)) if gsd else 0.0)
            if crown_area_geo_real is None:
                crown_area_geo_real = crown_area_geo_est
            if crown_area_geo is None:
                crown_area_geo = crown_area_geo_real

            conn.execute(
                "INSERT INTO tree_observations "
                "(obs_id, tract_id, run_id, species, confidence, box_px_sub, box_px_full, box_geo, "
                " crown_w_px, crown_h_px, crown_w_geo, crown_h_geo, "
                " height, height_source, center_geo, source_subimage_path, slice_size, geom_point, geom_crown, "
                " crown_area_px_est, crown_area_px_real, crown_area_geo_est, crown_area_geo_real, crown_volume_geo_est, crown_volume_geo_real) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (obs_id, tract_id, run_id, d.label, d.score,
                 json.dumps(box_px_sub) if box_px_sub else None,
                 json.dumps([d.x1, d.y1, d.x2, d.y2]),
                 box_geo,
                 d.width, d.height, crown_w_geo, crown_h_geo,
                 height, height_source,
                 center_geo, source_subimage_path, slice_size,
                 f"POINT({cx} {cy})", geom_crown,
                 crown_area_px_est, crown_area_px_real,
                 crown_area_geo_est, crown_area_geo_real,
                 crown_volume_geo_est, crown_volume_geo_real),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    log.info(
        "写「tree_observations」表: 本轮最终单木 {} 株 -> run_id={} slice_size={}",
        n, run_id, slice_size,
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
        log.info("多源登记: tract={} type={} path={}", tract_id, source_type, path)
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
                " geom_point, geom_crown, height, chosen_obs_id, active_run_id, "
                " crown_area_geo_est, crown_area_geo_real, crown_volume_geo_est, crown_volume_geo_real) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (canonical_id, tract_id, None, o.get("species"), o.get("confidence"),
                 o.get("geom_point"), o.get("geom_crown"),
                 o.get("height"), o.get("obs_id"), run_id,
                 o.get("crown_area_geo_est"), o.get("crown_area_geo_real"),
                 o.get("crown_volume_geo_est"), o.get("crown_volume_geo_real")),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    log.info("规范单木整理: {} 株 -> tract_id={} run_id={}", n, tract_id, run_id)
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
    log.info("个体持久化: {} 个体, 回填规范株 {} 条", n, linked)
    return n
