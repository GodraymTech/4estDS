from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

from forestds.api.routers.tracts import _tract_summary, get_observations, get_report
from forestds.db import reader, schema, writer
from forestds.export.formats import export_tract_to_file


PHASE_ID = "20260701"
TRACT_PK = "tract-pk"
TRACT_PHASE_PK = "phase-pk"


@pytest.fixture
def clean_db(tmp_path):
    db_file = tmp_path / "active-runs.db"
    db_url = f"sqlite:///{db_file}"
    schema.init_db(db_url)
    conn = sqlite3.connect(db_file)
    conn.execute(
        "INSERT INTO tracts "
        "(tract_pk, region_id, tract_id, boundary_geom, boundary_source, coverage_status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'auto', 'full', ?, ?)",
        (TRACT_PK, "region", "Q12", "POLYGON ((0 0, 2 0, 2 1, 0 1, 0 0))", "2026-07-01", "2026-07-01"),
    )
    conn.execute(
        "INSERT INTO tract_phases "
        "(tract_phase_pk, tract_pk, region_id, tract_id, phase_id, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (TRACT_PHASE_PK, TRACT_PK, "region", "Q12", PHASE_ID, "2026-07-01"),
    )
    conn.commit()
    conn.close()
    return db_url


def seed_two_tiffs_same_phase(db_url: str) -> tuple[str, str]:
    conn = _connect(db_url)
    for index, tiff_id in enumerate(("tif01", "tif02"), start=1):
        conn.execute(
            "INSERT INTO tiffs "
            "(tiff_id, phase_id, tract_phase_pk, file_name, path_versions, footprint_geom, "
            "geo_area, area_unit, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                tiff_id,
                PHASE_ID,
                TRACT_PHASE_PK,
                f"image-{index}.tif",
                json.dumps({"v1": f"/data/image-{index}.tif"}),
                f"POLYGON (({index - 1} 0, {index} 0, {index} 1, {index - 1} 1, {index - 1} 0))",
                10000.0,
                "m2",
                f"2026-07-01T00:0{index}:00",
                f"2026-07-01T00:0{index}:00",
            ),
        )
    conn.commit()
    conn.close()
    return "tif01", "tif02"


def seed_run(
    db_url: str,
    run_id: str,
    tiff_id: str | None,
    *,
    status: str = "succeeded",
    task_type: str = "infer",
    minute: int = 1,
    observations: int = 0,
) -> str:
    conn = _connect(db_url)
    phase_id = PHASE_ID if tiff_id else None
    conn.execute(
        "INSERT INTO runs "
        "(run_id, tract_phase_pk, tiff_id, phase_id, task_type, status, started_at, ended_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            TRACT_PHASE_PK,
            tiff_id,
            phase_id,
            task_type,
            status,
            f"2026-07-01T00:{minute:02d}:00",
            f"2026-07-01T00:{minute:02d}:30" if status not in {"queued", "running"} else None,
            f"2026-07-01T00:{minute:02d}:00",
        ),
    )
    for index in range(observations):
        conn.execute(
            "INSERT INTO tree_observations "
            "(observation_id, run_id, tract_phase_pk, tiff_id, phase_id, species, confidence, center_geom, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"{run_id}-obs-{index}",
                run_id,
                TRACT_PHASE_PK,
                tiff_id,
                PHASE_ID,
                "tree",
                0.9,
                f"POINT ({index + 0.25} 0.5)",
                f"2026-07-01T00:{minute:02d}:20",
            ),
        )
    conn.commit()
    conn.close()
    return run_id


def active_run(db_url: str, tiff_id: str) -> str | None:
    conn = _connect(db_url)
    row = conn.execute(
        "SELECT active_run_id FROM tiffs WHERE phase_id=? AND tiff_id=?",
        (PHASE_ID, tiff_id),
    ).fetchone()
    conn.close()
    return row[0] if row else None


def table_columns(db_url: str, table: str) -> set[str]:
    conn = _connect(db_url)
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    conn.close()
    return columns


def test_each_tiff_has_independent_active_run(clean_db):
    first, second = seed_two_tiffs_same_phase(clean_db)
    run_a = seed_run(clean_db, "run001", first)
    run_b = seed_run(clean_db, "run002", second)

    writer.promote_run(run_a, url=clean_db)
    writer.promote_run(run_b, url=clean_db)

    assert active_run(clean_db, first) == run_a
    assert active_run(clean_db, second) == run_b
    assert "active_run_id" not in table_columns(clean_db, "tract_phases")
    assert "active_run_id" in table_columns(clean_db, "tiffs")


def test_promote_rejects_non_succeeded_and_run_without_tiff(clean_db):
    first, _ = seed_two_tiffs_same_phase(clean_db)
    failed = seed_run(clean_db, "run003", first, status="failed")
    missing_tiff = seed_run(clean_db, "run004", None)

    with pytest.raises(ValueError, match="只有成功"):
        writer.promote_run(failed, url=clean_db)
    with pytest.raises(ValueError, match="TIFF"):
        writer.promote_run(missing_tiff, url=clean_db)

    assert active_run(clean_db, first) is None


def test_unpublished_run_does_not_affect_map_statistics_or_export(clean_db, tmp_path):
    first, _ = seed_two_tiffs_same_phase(clean_db)
    active = seed_run(clean_db, "run005", first, minute=1, observations=1)
    seed_run(clean_db, "run006", first, minute=2, observations=3)
    writer.promote_run(active, url=clean_db)

    response = get_observations(TRACT_PHASE_PK, run_id=None, geometry="point", db_url=clean_db)
    payload = json.loads(response.body)
    assert [feature["properties"]["run_id"] for feature in payload["features"]] == [active]

    summary = _tract_summary(TRACT_PHASE_PK, clean_db)
    assert summary["tree_count"] == 1

    exported = export_tract_to_file(
        tract_id=TRACT_PHASE_PK,
        fmt="csv",
        out_path=tmp_path / "official.csv",
        db_url=clean_db,
    )
    assert exported["count"] == 1


def test_asset_ledger_aggregates_runs_for_only_the_same_tiff(clean_db):
    from forestds.api.routers.assets import list_assets

    first, second = seed_two_tiffs_same_phase(clean_db)
    active = seed_run(clean_db, "run007", first, minute=1, observations=2)
    seed_run(clean_db, "run008", first, status="failed", minute=2)
    seed_run(clean_db, "run009", first, status="running", task_type="review", minute=3)
    seed_run(clean_db, "run010", first, status="succeeded", task_type="train", minute=4)
    seed_run(clean_db, "run011", second, status="succeeded", minute=5, observations=4)
    writer.promote_run(active, url=clean_db)

    row = next(item for item in reader.list_tiffs(url=clean_db) if item["tiff_id"] == first)

    assert row["active_run_id"] == active
    assert row["run_id"] == active
    assert row["run_count"] == 3
    assert row["run_status_counts"] == {"succeeded": 1, "failed": 1, "running": 1}
    assert row["active_run_status"] == "succeeded"
    assert row["observation_count"] == 2
    assert row["detected_at"] == "2026-07-01T00:01:30"

    asset = next(item for item in list_assets(db_url=clean_db) if item.tiff_id == first)
    assert asset.active_run_id == active
    assert asset.run_count == 3
    assert asset.run_status_counts == {"succeeded": 1, "failed": 1, "running": 1}
    assert reader.get_tract(TRACT_PHASE_PK, url=clean_db)["active_run_id"] == active


def test_job_history_filters_by_phase_and_tiff(clean_db):
    from forestds.api.routers.jobs import list_jobs

    first, second = seed_two_tiffs_same_phase(clean_db)
    seed_run(clean_db, "run012", first)
    seed_run(clean_db, "run013", second)

    jobs = reader.list_runs(
        url=clean_db,
        task_type=None,
        phase_id=PHASE_ID,
        tiff_id=first,
        limit=50,
    )

    assert [job["run_id"] for job in jobs] == ["run012"]
    assert jobs[0]["phase_id"] == PHASE_ID
    assert jobs[0]["tiff_id"] == first

    api_jobs = list_jobs(
        task_type=None,
        phase_id=PHASE_ID,
        tiff_id=first,
        limit=50,
        db_url=clean_db,
    )
    assert [job.run_id for job in api_jobs] == ["run012"]


def test_tiff_history_filter_includes_only_infer_and_review_runs(clean_db):
    from forestds.api.routers.jobs import list_jobs

    first, _ = seed_two_tiffs_same_phase(clean_db)
    seed_run(clean_db, "run015", first, task_type="infer", minute=2)
    seed_run(clean_db, "run016", first, task_type="review", minute=3)
    seed_run(clean_db, "run017", first, task_type="train", minute=4)

    jobs = list_jobs(
        task_type="infer,review",
        phase_id=PHASE_ID,
        tiff_id=first,
        limit=50,
        db_url=clean_db,
    )

    assert [job.run_id for job in jobs] == ["run016", "run015"]
    assert {job.task_type for job in jobs} == {"infer", "review"}


def test_report_without_active_run_returns_not_found_instead_of_name_error(clean_db):
    with pytest.raises(HTTPException) as exc_info:
        get_report(TRACT_PHASE_PK, run_id=None, fmt="md", db_url=clean_db)

    assert exc_info.value.status_code == 404
    assert "尚无可用运行" in str(exc_info.value.detail)


def test_review_is_a_valid_run_task_type(clean_db):
    first, _ = seed_two_tiffs_same_phase(clean_db)
    seed_run(clean_db, "run014", first, task_type="review")


def test_postgis_schema_uses_tiff_active_run_contract():
    sql = (Path(__file__).parents[1] / "deploy/postgis/schema.sql").read_text(encoding="utf-8")

    tract_phases = _create_table_sql(sql, "tract_phases")
    tiffs = _create_table_sql(sql, "tiffs")
    runs = _create_table_sql(sql, "runs")
    observations = _create_table_sql(sql, "tree_observations")

    assert "active_run_id" not in tract_phases
    assert "active_run_id" in tiffs
    assert "REFERENCES runs(run_id) ON DELETE SET NULL" in tiffs
    assert "'review'" in runs
    assert "phase_id               TEXT," in observations
    assert "FOREIGN KEY (tiff_id, phase_id)" in observations
    assert "REFERENCES tiffs(tiff_id, phase_id) ON DELETE SET NULL" in observations
    assert "END;\n$$;" in sql


def _connect(db_url: str) -> sqlite3.Connection:
    conn = sqlite3.connect(schema.resolve_db_path(db_url))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _create_table_sql(sql: str, table: str) -> str:
    marker = f"CREATE TABLE IF NOT EXISTS {table} ("
    assert marker in sql, f"PostGIS schema 缺少 {table} 表"
    start = sql.index(marker)
    end = sql.index("\n);", start) + 3
    return sql[start:end]
