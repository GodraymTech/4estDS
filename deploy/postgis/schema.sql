-- 4estDS PostGIS 模式 (v1.0 部署目标)
-- ------------------------------------------------------------------
-- 与 src/forestds/db/schema.py 的 SQLite 六表结构一一对应，差异仅在:
--   1) 几何列使用 PostGIS 原生 geometry 类型 (替代 WKT/GeoJSON TEXT)
--   2) 几何列建立 GiST 空间索引 (空间查询/瓦片裁剪性能)
-- SRID 采用 0 (未定 CRS)，每行几何由 ST_GeomFromText(wkt, srid) 按地块 crs_epsg 写入；
-- 如全库统一投影坐标系，可将 0 改为对应 EPSG 并加约束。
-- 该脚本幂等 (IF NOT EXISTS)，可安全重复执行。

CREATE EXTENSION IF NOT EXISTS postgis;

-- 运行日志 (作业状态单一真相)
CREATE TABLE IF NOT EXISTS run_logs (
    run_id        TEXT PRIMARY KEY,
    parent_run_id TEXT,
    tag           TEXT,
    task_type     TEXT NOT NULL,
    model_arch    TEXT,
    status        TEXT NOT NULL DEFAULT 'running',
    started_at    TEXT NOT NULL,
    ended_at      TEXT,
    duration_s    DOUBLE PRECISION,
    input_path    TEXT,
    tiles_dir     TEXT,
    params_json   TEXT,
    metrics_json  TEXT,
    error         TEXT,
    host          TEXT
);

-- 跨时相独立个体
CREATE TABLE IF NOT EXISTS tree_individuals (
    individual_id    TEXT PRIMARY KEY,
    location_cluster TEXT,
    first_seen       TEXT,
    last_seen        TEXT,
    status           TEXT DEFAULT 'alive'
);

-- 地块
CREATE TABLE IF NOT EXISTS tracts (
    tract_id         TEXT PRIMARY KEY,
    name             TEXT,
    acquisition_time TEXT,
    location         TEXT,
    pixel_w          INTEGER,
    pixel_h          INTEGER,
    gsd              DOUBLE PRECISION,
    geo_area         DOUBLE PRECISION,
    area_unit        TEXT,
    crs_epsg         INTEGER,
    crs_wkt          TEXT,
    footprint_geom   geometry(Polygon, 0),
    active_run_id    TEXT REFERENCES run_logs(run_id) ON DELETE SET NULL,
    UNIQUE (acquisition_time, location)
);

-- 地块数据源
CREATE TABLE IF NOT EXISTS tract_sources (
    source_id   TEXT PRIMARY KEY,
    tract_id    TEXT NOT NULL REFERENCES tracts(tract_id) ON DELETE CASCADE,
    kind        TEXT,
    path        TEXT,
    meta_json   TEXT
);

-- 单木观测 (每 run 一批)
CREATE TABLE IF NOT EXISTS tree_observations (
    obs_id                TEXT PRIMARY KEY,
    tract_id              TEXT NOT NULL REFERENCES tracts(tract_id) ON DELETE CASCADE,
    run_id                TEXT NOT NULL REFERENCES run_logs(run_id) ON DELETE CASCADE,
    species               TEXT,
    confidence            DOUBLE PRECISION,
    box_px_sub            TEXT,
    box_px_full           TEXT,
    box_geo               TEXT,
    crown_w_px            DOUBLE PRECISION,
    crown_h_px            DOUBLE PRECISION,
    crown_w_geo           DOUBLE PRECISION,
    crown_h_geo           DOUBLE PRECISION,
    height                DOUBLE PRECISION,
    height_source         TEXT,
    center_geo            TEXT,
    source_subimage_path  TEXT,
    slice_size            INTEGER,
    geom_point            geometry(Point, 0),
    geom_crown            geometry(Polygon, 0),
    crown_area_px_est     DOUBLE PRECISION,
    crown_area_px_real    DOUBLE PRECISION,
    crown_area_geo_est    DOUBLE PRECISION,
    crown_area_geo_real   DOUBLE PRECISION,
    crown_volume_geo_est  DOUBLE PRECISION,
    crown_volume_geo_real DOUBLE PRECISION
);

-- 地块规范单木 (同一时相择优)
CREATE TABLE IF NOT EXISTS tract_trees (
    canonical_id          TEXT PRIMARY KEY,
    tract_id              TEXT NOT NULL REFERENCES tracts(tract_id) ON DELETE CASCADE,
    individual_id         TEXT REFERENCES tree_individuals(individual_id) ON DELETE SET NULL,
    species               TEXT,
    confidence            DOUBLE PRECISION,
    geom_point            geometry(Point, 0),
    geom_crown            geometry(Polygon, 0),
    height                DOUBLE PRECISION,
    chosen_obs_id         TEXT REFERENCES tree_observations(obs_id) ON DELETE SET NULL,
    active_run_id         TEXT REFERENCES run_logs(run_id) ON DELETE SET NULL,
    crown_area_geo_est    DOUBLE PRECISION,
    crown_area_geo_real   DOUBLE PRECISION,
    crown_volume_geo_est  DOUBLE PRECISION,
    crown_volume_geo_real DOUBLE PRECISION
);

-- 常用索引 (与 SQLite 对齐 + 空间 GiST)
CREATE INDEX IF NOT EXISTS idx_obs_tract      ON tree_observations(tract_id);
CREATE INDEX IF NOT EXISTS idx_obs_run        ON tree_observations(run_id);
CREATE INDEX IF NOT EXISTS idx_canon_tract    ON tract_trees(tract_id);
CREATE INDEX IF NOT EXISTS idx_obs_geom       ON tree_observations USING GIST (geom_point);
CREATE INDEX IF NOT EXISTS idx_obs_crown_geom ON tree_observations USING GIST (geom_crown);
CREATE INDEX IF NOT EXISTS idx_canon_geom     ON tract_trees USING GIST (geom_point);
CREATE INDEX IF NOT EXISTS idx_tract_foot     ON tracts USING GIST (footprint_geom);
