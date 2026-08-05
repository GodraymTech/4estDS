"""SQLite schema for the tract -> phase -> TIFF -> tree observation model."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .. import paths

_CORE_TABLES = (
    "review_sessions",
    "tree_observations",
    "tree_individuals",
    "runs",
    "tiffs",
    "tract_phases",
    "tracts",
)

DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS tracts (
        tract_pk        TEXT PRIMARY KEY,
        region_id       TEXT NOT NULL,
        city            TEXT,
        county          TEXT,
        town            TEXT,
        tract_id        TEXT NOT NULL,
        boundary_geom   TEXT,
        boundary_geom_cent TEXT,
        effective_geom  TEXT,
        effective_area_hm2 REAL,
        effective_source TEXT NOT NULL DEFAULT 'default'
            CHECK (effective_source IN ('default', 'manual')),
        coverage_status TEXT NOT NULL DEFAULT 'none'
            CHECK (coverage_status IN ('none', 'partial', 'full')),
        notes           TEXT,
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL,
        UNIQUE (region_id, tract_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS review_sessions (
        session_id          TEXT PRIMARY KEY,
        phase_id            TEXT NOT NULL,
        tiff_id             TEXT NOT NULL,
        tract_phase_pk      TEXT NOT NULL REFERENCES tract_phases(tract_phase_pk) ON DELETE CASCADE,
        mode                TEXT NOT NULL CHECK (mode IN ('inherit', 'fresh')),
        base_run_id         TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
        expected_active_run_id TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
        status              TEXT NOT NULL DEFAULT 'active'
            CHECK (status IN ('active', 'published', 'canceled')),
        revision            INTEGER NOT NULL DEFAULT 0,
        draft_path          TEXT NOT NULL,
        summary_json        TEXT,
        published_run_id    TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
        created_at          TEXT NOT NULL,
        updated_at          TEXT NOT NULL,
        FOREIGN KEY (tiff_id, phase_id) REFERENCES tiffs(tiff_id, phase_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tract_phases (
        tract_phase_pk  TEXT PRIMARY KEY,
        tract_pk        TEXT NOT NULL REFERENCES tracts(tract_pk) ON DELETE CASCADE,
        region_id       TEXT NOT NULL,
        tract_id        TEXT NOT NULL,
        phase_id        TEXT NOT NULL
            CHECK (phase_id GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'),
        area_hm2        REAL DEFAULT 0.0,
        updated_at      TEXT NOT NULL,
        UNIQUE (tract_pk, phase_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tiffs (
        tiff_id                    TEXT NOT NULL CHECK (length(tiff_id) = 5),
        phase_id                   TEXT NOT NULL
            CHECK (phase_id GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'),
        tract_phase_pk             TEXT NOT NULL REFERENCES tract_phases(tract_phase_pk) ON DELETE CASCADE,
        file_name                  TEXT,
        path_versions              TEXT NOT NULL DEFAULT '{}',
        multisource_path_versions  TEXT NOT NULL DEFAULT '{}',
        tiff_type                  TEXT NOT NULL DEFAULT 'invalid'
            CHECK (tiff_type IN ('normal', 'tiled', 'ext_ovr', 'COG', 'invalid')),
        footprint_geom             TEXT NOT NULL,
        footprint_bbox             TEXT,
        center_geom                TEXT,
        crs_epsg                   INTEGER,
        crs_wkt                    TEXT,
        geotransform               TEXT,
        pixel_width                INTEGER,
        pixel_height               INTEGER,
        gsd                        REAL,
        footprint_area_hm2         REAL,
        area_hm2                   REAL,
        effective_area_hm2         REAL,
        band_count                 INTEGER,
        dtype                      TEXT,
        nodata                     REAL,
        inference_status           TEXT NOT NULL DEFAULT 'pending'
            CHECK (inference_status IN ('pending', 'inferred')),
        active_run_id               TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
        created_at                 TEXT NOT NULL,
        updated_at                 TEXT NOT NULL,
        PRIMARY KEY (tiff_id, phase_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runs (
        run_id          TEXT PRIMARY KEY CHECK (length(run_id) = 6),
        parent_run_id   TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
        tag             TEXT,
        tract_phase_pk  TEXT REFERENCES tract_phases(tract_phase_pk) ON DELETE SET NULL,
        tiff_id         TEXT,
        phase_id        TEXT,
        task_type       TEXT NOT NULL
            CHECK (task_type IN ('infer', 'review', 'train', 'report', 'batch', 'export', 'postprocess', 'import', 'track')),
        model_arch      TEXT,
        status          TEXT NOT NULL DEFAULT 'running'
            CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'canceled')),
        slice_size      INTEGER,
        input_path      TEXT,
        tiles_dir       TEXT,
        input_json      TEXT,
        params_json     TEXT,
        metrics_json    TEXT,
        error           TEXT,
        host            TEXT,
        started_at      TEXT NOT NULL,
        ended_at        TEXT,
        duration_s      REAL,
        created_at      TEXT NOT NULL,
        FOREIGN KEY (tiff_id, phase_id) REFERENCES tiffs(tiff_id, phase_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tree_individuals (
        individual_id        TEXT PRIMARY KEY CHECK (length(individual_id) = 8),
        first_seen_phase_id  TEXT,
        last_seen_phase_id   TEXT,
        global_status        TEXT NOT NULL DEFAULT 'alive'
            CHECK (global_status IN ('alive', 'missing', 'removed', 'unknown')),
        tracking_confidence  REAL,
        growth_json          TEXT,
        created_at           TEXT NOT NULL,
        updated_at           TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tree_observations (
        observation_id         TEXT PRIMARY KEY,
        individual_id          TEXT REFERENCES tree_individuals(individual_id) ON DELETE SET NULL,
        run_id                 TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
        tract_phase_pk         TEXT NOT NULL REFERENCES tract_phases(tract_phase_pk) ON DELETE CASCADE,
        tiff_id                TEXT,
        phase_id               TEXT,
        species                TEXT,
        confidence             REAL,
        center_geom            TEXT,
        crown_geom             TEXT,
        box_px                 TEXT,
        box_px_sub             TEXT,
        box_geo                TEXT,
        crown_width_px         REAL,
        crown_height_px        REAL,
        crown_width_geo        REAL,
        crown_height_geo       REAL,
        crown_area_px          REAL,
        crown_area_geo_est     REAL,
        crown_area_geo_real    REAL,
        height                 REAL,
        height_source          TEXT,
        crown_volume_geo_est   REAL,
        crown_volume_geo_real  REAL,
        source_subimage_path   TEXT,
        slice_size             INTEGER,
        geom_point             TEXT,
        geom_crown             TEXT,
        created_at             TEXT NOT NULL,
        FOREIGN KEY (tiff_id, phase_id) REFERENCES tiffs(tiff_id, phase_id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_tracts_region ON tracts(region_id)",
    "CREATE INDEX IF NOT EXISTS idx_tract_phases_tract ON tract_phases(tract_pk, phase_id)",
    "CREATE INDEX IF NOT EXISTS idx_tiffs_tract_phase ON tiffs(tract_phase_pk)",
    "CREATE INDEX IF NOT EXISTS idx_runs_tract_phase ON runs(tract_phase_pk, status)",
    "CREATE INDEX IF NOT EXISTS idx_obs_run ON tree_observations(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_obs_tract_phase ON tree_observations(tract_phase_pk)",
    "CREATE INDEX IF NOT EXISTS idx_obs_individual ON tree_observations(individual_id)",
    "CREATE INDEX IF NOT EXISTS idx_review_sessions_tiff ON review_sessions(phase_id, tiff_id, status)",
)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _assert_new_schema(conn: sqlite3.Connection) -> None:
    """Fail fast on incompatible pre-refactor databases instead of renaming tables."""
    if _table_exists(conn, "run_logs") or _table_exists(conn, "tract_sources") or _table_exists(conn, "tract_trees"):
        raise RuntimeError("检测到旧版数据库表；请先备份并创建新的 4estDS 数据库。")
    required = {
        "tracts": {
            "tract_pk",
            "region_id",
            "tract_id",
            "boundary_geom_cent",
            "effective_geom",
            "effective_area_hm2",
            "effective_source",
        },
        "tract_phases": {"tract_phase_pk", "tract_pk", "phase_id"},
        "tiffs": {"tiff_id", "phase_id", "tract_phase_pk", "center_geom", "footprint_area_hm2", "area_hm2", "tiff_type", "active_run_id"},
        "runs": {"run_id", "tract_phase_pk", "task_type"},
        "tree_observations": {"observation_id", "run_id", "tract_phase_pk"},
        "review_sessions": {"session_id", "phase_id", "tiff_id", "revision", "draft_path"},
    }
    for table, columns in required.items():
        if _table_exists(conn, table) and not columns.issubset(_table_columns(conn, table)):
            raise RuntimeError(f"数据库表 {table} 不符合新 schema；请使用干净数据库重新初始化。")
    if _table_exists(conn, "tract_phases") and "active_run_id" in _table_columns(conn, "tract_phases"):
        raise RuntimeError("数据库表 tract_phases 仍含 active_run_id；请使用干净数据库重新初始化。")


def resolve_db_path(url: str | None = None) -> Path:
    """解析 sqlite 文件路径(仅支持本地文件型 URL 或 None)。"""
    if url and url.startswith("sqlite"):
        tail = url.split(":///", 1)[-1]
        return Path(tail).expanduser()
    return paths.default_db_path()


def _fix_review_sessions_schema(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "review_sessions"):
        return
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='review_sessions'"
    ).fetchone()
    if row and row[0] and ("based_on_active" in row[0] or "from_scratch" in row[0]):
        conn.execute("DROP TABLE review_sessions")


def init_db(url: str | None = None) -> Path:
    """创建新数据库表；自动升级旧 schema。"""
    db_path = resolve_db_path(url)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        _fix_review_sessions_schema(conn)
        _assert_new_schema(conn)
        for stmt in DDL:
            conn.execute(stmt)
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
