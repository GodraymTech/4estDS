-- 4estDS PostGIS schema for the tract -> phase -> TIFF -> run model.
-- New databases only: this file intentionally carries no legacy migration path.

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS tracts (
    tract_pk            TEXT PRIMARY KEY,
    region_id           TEXT NOT NULL,
    city                TEXT,
    county              TEXT,
    town                TEXT,
    tract_id            TEXT NOT NULL,
    boundary_geom       geometry(Geometry, 0),
    boundary_geom_cent  geometry(Point, 0),
    effective_geom      geometry(MultiPolygon, 4326),
    effective_area_hm2 DOUBLE PRECISION,
    boundary_source     TEXT NOT NULL DEFAULT 'auto'
        CHECK (boundary_source IN ('auto', 'manual')),
    coverage_status     TEXT NOT NULL DEFAULT 'none'
        CHECK (coverage_status IN ('none', 'partial', 'full')),
    notes               TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE (region_id, tract_id)
);

CREATE TABLE IF NOT EXISTS tract_phases (
    tract_phase_pk  TEXT PRIMARY KEY,
    tract_pk        TEXT NOT NULL REFERENCES tracts(tract_pk) ON DELETE CASCADE,
    region_id       TEXT NOT NULL,
    tract_id        TEXT NOT NULL,
    phase_id        TEXT NOT NULL CHECK (phase_id ~ '^[0-9]{8}$'),
    boundary_geom   geometry(Geometry, 0),
    updated_at      TEXT NOT NULL,
    UNIQUE (tract_pk, phase_id)
);

-- runs is created before tiffs so tiffs.active_run_id can be declared inline.
-- The reverse composite runs -> tiffs foreign key is added after tiffs exists.
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
    duration_s      DOUBLE PRECISION,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tiffs (
    tiff_id                    TEXT NOT NULL CHECK (length(tiff_id) = 5),
    phase_id                   TEXT NOT NULL CHECK (phase_id ~ '^[0-9]{8}$'),
    tract_phase_pk             TEXT NOT NULL REFERENCES tract_phases(tract_phase_pk) ON DELETE CASCADE,
    file_name                  TEXT,
    path_versions              TEXT NOT NULL DEFAULT '{}',
    multisource_path_versions  TEXT NOT NULL DEFAULT '{}',
    tiff_type                  TEXT NOT NULL DEFAULT 'invalid'
        CHECK (tiff_type IN ('normal', 'tiled', 'ext_ovr', 'COG', 'invalid')),
    footprint_geom             geometry(Geometry, 0) NOT NULL,
    footprint_bbox             TEXT,
    center_geom                geometry(Point, 0),
    center_lng                 DOUBLE PRECISION,
    center_lat                 DOUBLE PRECISION,
    crs_epsg                   INTEGER,
    crs_wkt                    TEXT,
    geotransform               TEXT,
    pixel_width                INTEGER,
    pixel_height               INTEGER,
    gsd                        DOUBLE PRECISION,
    geo_area                   DOUBLE PRECISION,
    area_unit                  TEXT,
    band_count                 INTEGER,
    dtype                      TEXT,
    nodata                     DOUBLE PRECISION,
    inference_status           TEXT NOT NULL DEFAULT 'pending'
        CHECK (inference_status IN ('pending', 'inferred')),
    active_run_id              TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
    created_at                 TEXT NOT NULL,
    updated_at                 TEXT NOT NULL,
    PRIMARY KEY (tiff_id, phase_id)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_runs_tiff' AND conrelid = 'runs'::regclass
    ) THEN
        ALTER TABLE runs
            ADD CONSTRAINT fk_runs_tiff
            FOREIGN KEY (tiff_id, phase_id)
            REFERENCES tiffs(tiff_id, phase_id)
            ON DELETE SET NULL;
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS tree_individuals (
    individual_id        TEXT PRIMARY KEY CHECK (length(individual_id) = 8),
    first_seen_phase_id  TEXT,
    last_seen_phase_id   TEXT,
    global_status        TEXT NOT NULL DEFAULT 'alive'
        CHECK (global_status IN ('alive', 'missing', 'removed', 'unknown')),
    tracking_confidence  DOUBLE PRECISION,
    growth_json          TEXT,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tree_observations (
    observation_id         TEXT PRIMARY KEY,
    individual_id          TEXT REFERENCES tree_individuals(individual_id) ON DELETE SET NULL,
    run_id                 TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    tract_phase_pk         TEXT NOT NULL REFERENCES tract_phases(tract_phase_pk) ON DELETE CASCADE,
    tiff_id                TEXT,
    phase_id               TEXT,
    species                TEXT,
    confidence             DOUBLE PRECISION,
    center_geom            geometry(Point, 0),
    crown_geom             geometry(Geometry, 0),
    box_px                 TEXT,
    box_px_sub             TEXT,
    box_geo                TEXT,
    crown_width_px         DOUBLE PRECISION,
    crown_height_px        DOUBLE PRECISION,
    crown_width_geo        DOUBLE PRECISION,
    crown_height_geo       DOUBLE PRECISION,
    crown_area_px          DOUBLE PRECISION,
    crown_area_geo_est     DOUBLE PRECISION,
    crown_area_geo_real    DOUBLE PRECISION,
    height                 DOUBLE PRECISION,
    height_source          TEXT,
    crown_volume_geo_est   DOUBLE PRECISION,
    crown_volume_geo_real  DOUBLE PRECISION,
    source_subimage_path   TEXT,
    slice_size             INTEGER,
    geom_point             geometry(Point, 0),
    geom_crown             geometry(Geometry, 0),
    created_at             TEXT NOT NULL,
    FOREIGN KEY (tiff_id, phase_id)
        REFERENCES tiffs(tiff_id, phase_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS review_sessions (
    session_id          TEXT PRIMARY KEY,
    phase_id            TEXT NOT NULL,
    tiff_id             TEXT NOT NULL,
    tract_phase_pk      TEXT NOT NULL REFERENCES tract_phases(tract_phase_pk) ON DELETE CASCADE,
    mode                TEXT NOT NULL CHECK (mode IN ('based_on_active', 'from_scratch')),
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
    FOREIGN KEY (tiff_id, phase_id)
        REFERENCES tiffs(tiff_id, phase_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tracts_region ON tracts(region_id);
CREATE INDEX IF NOT EXISTS idx_tract_phases_tract ON tract_phases(tract_pk, phase_id);
CREATE INDEX IF NOT EXISTS idx_tiffs_tract_phase ON tiffs(tract_phase_pk);
CREATE INDEX IF NOT EXISTS idx_runs_tract_phase ON runs(tract_phase_pk, status);
CREATE INDEX IF NOT EXISTS idx_obs_run ON tree_observations(run_id);
CREATE INDEX IF NOT EXISTS idx_obs_tract_phase ON tree_observations(tract_phase_pk);
CREATE INDEX IF NOT EXISTS idx_obs_individual ON tree_observations(individual_id);
CREATE INDEX IF NOT EXISTS idx_review_sessions_tiff ON review_sessions(phase_id, tiff_id, status);
CREATE INDEX IF NOT EXISTS idx_tracts_boundary_geom ON tracts USING GIST (boundary_geom);
CREATE INDEX IF NOT EXISTS idx_tracts_effective_geom ON tracts USING GIST (effective_geom);
CREATE INDEX IF NOT EXISTS idx_tiffs_footprint_geom ON tiffs USING GIST (footprint_geom);
CREATE INDEX IF NOT EXISTS idx_obs_geom_point ON tree_observations USING GIST (geom_point);
CREATE INDEX IF NOT EXISTS idx_obs_geom_crown ON tree_observations USING GIST (geom_crown);
