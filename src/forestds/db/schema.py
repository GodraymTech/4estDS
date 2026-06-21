"""用标准库 sqlite3 创建三层单木模型。

三层设计(解决"重复推理污染")::

    tree_observations  原始观测(可重复,每次 run/每个切片都记录)
          |  同一时相择优去重
          v
    tract_trees        地块规范单木(某时相的"权威"株)
          |  跨时相同株匹配
          v
    tree_individuals   跨时相独立个体(生命周期/生长轨迹)

该函数仅建表;几何列以 WKT/GeoJSON 文本存储,迁移 PostGIS 后转为原生几何。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .. import paths

# 按依赖顺序组织的建表语句
DDL: tuple[str, ...] = (
    # run 谱:所有任务的运行记录(可追溯、可复现)
    """
    CREATE TABLE IF NOT EXISTS run_logs (
        run_id        TEXT PRIMARY KEY,
        parent_run_id TEXT,
        tag           TEXT,
        task_type     TEXT NOT NULL,
        model_arch    TEXT,
        status        TEXT NOT NULL DEFAULT 'running',
        started_at    TEXT NOT NULL,
        ended_at      TEXT,
        duration_s    REAL,
        input_path    TEXT,
        tiles_dir     TEXT,
        params_json   TEXT,
        metrics_json  TEXT,
        error         TEXT,
        host          TEXT
    )
    """,
    # 跨时相独立个体(生命周期跟踪)
    """
    CREATE TABLE IF NOT EXISTS tree_individuals (
        individual_id   TEXT PRIMARY KEY,
        location_cluster TEXT,
        first_seen      TEXT,
        last_seen       TEXT,
        status          TEXT DEFAULT 'alive',
        growth_json     TEXT
    )
    """,
    # 地块(一幅影像): acquisition_time(YYYYMM) + location 联合唯一
    """
    CREATE TABLE IF NOT EXISTS tracts (
        tract_id         TEXT PRIMARY KEY,
        owner_ref        TEXT,
        name             TEXT,
        acquisition_time TEXT NOT NULL,
        location         TEXT NOT NULL,
        pixel_w          INTEGER,
        pixel_h          INTEGER,
        gsd              REAL,
        geo_area         REAL,
        area_unit        TEXT,
        crs_epsg         INTEGER,
        geotransform     TEXT,
        bounds_bbox      TEXT,
        nodata           REAL,
        band_count       INTEGER,
        dtype            TEXT,
        footprint_geom   TEXT,
        status           TEXT DEFAULT 'registered',
        notes            TEXT,
        UNIQUE (acquisition_time, location)
    )
    """,
    # 地块多源文件(RGB/CHM/多光谱等)
    """
    CREATE TABLE IF NOT EXISTS tract_sources (
        source_id   TEXT PRIMARY KEY,
        tract_id    TEXT NOT NULL REFERENCES tracts(tract_id) ON DELETE CASCADE,
        source_type TEXT NOT NULL,
        path        TEXT NOT NULL,
        meta_json   TEXT
    )
    """,
    # 原始观测(可重复)
    """
    CREATE TABLE IF NOT EXISTS tree_observations (
        obs_id              TEXT PRIMARY KEY,
        tract_id            TEXT NOT NULL REFERENCES tracts(tract_id) ON DELETE CASCADE,
        run_id              TEXT NOT NULL REFERENCES run_logs(run_id) ON DELETE CASCADE,
        species             TEXT,
        confidence          REAL,
        box_px_sub          TEXT,
        box_px_full         TEXT,
        box_geo             TEXT,
        crown_w_px          REAL,
        crown_h_px          REAL,
        crown_area_px       REAL,
        crown_w_geo         REAL,
        crown_h_geo         REAL,
        crown_area_geo      REAL,
        height              REAL,
        height_source       TEXT,
        center_geo          TEXT,
        source_subimage_path TEXT,
        slice_size          INTEGER,
        geom_point          TEXT,
        geom_crown          TEXT
    )
    """,
    # 地块规范单木(同一时相择优)
    """
    CREATE TABLE IF NOT EXISTS tract_trees (
        canonical_id  TEXT PRIMARY KEY,
        tract_id      TEXT NOT NULL REFERENCES tracts(tract_id) ON DELETE CASCADE,
        individual_id TEXT REFERENCES tree_individuals(individual_id) ON DELETE SET NULL,
        species       TEXT,
        confidence    REAL,
        geom_point    TEXT,
        geom_crown    TEXT,
        height        REAL,
        crown         REAL,
        chosen_obs_id TEXT REFERENCES tree_observations(obs_id) ON DELETE SET NULL,
        active_run_id TEXT REFERENCES run_logs(run_id) ON DELETE SET NULL
    )
    """,
    # 常用索引
    "CREATE INDEX IF NOT EXISTS idx_obs_tract ON tree_observations(tract_id)",
    "CREATE INDEX IF NOT EXISTS idx_obs_run ON tree_observations(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_canon_tract ON tract_trees(tract_id)",
    "CREATE INDEX IF NOT EXISTS idx_canon_individual ON tract_trees(individual_id)",
)


def resolve_db_path(url: str | None = None) -> Path:
    """解析 sqlite 文件路径(仅支持本地文件型 URL 或 None)。"""
    if url and url.startswith("sqlite"):
        # sqlite:///abs/path 或 sqlite:////abs/path
        tail = url.split(":///", 1)[-1]
        return Path(tail).expanduser()
    return paths.default_db_path()


def init_db(url: str | None = None) -> Path:
    """创建所有表与索引。返回 sqlite 文件路径。"""
    db_path = resolve_db_path(url)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        for stmt in DDL:
            conn.execute(stmt)
        # 向后兼容迁移：为旧库补充 tiles_dir 列（SQLite 不支持 IF NOT EXISTS，忽略重复错误）
        try:
            conn.execute("ALTER TABLE run_logs ADD COLUMN tiles_dir TEXT")
        except sqlite3.OperationalError:
            pass  # 列已存在，无需处理
        conn.commit()
    finally:
        conn.close()
    return db_path


def table_names(url: str | None = None) -> list[str]:
    """返回现有表名(供测试/调试)。"""
    db_path = resolve_db_path(url)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]
