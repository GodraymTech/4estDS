from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException
from pyproj import Geod, Transformer
from shapely.geometry import MultiPolygon, Polygon, box, mapping, shape
from shapely.ops import orient
from shapely.wkt import loads as load_wkt

from forestds.api.routers.tracts import get_effective_area, put_effective_area
from forestds.api.routers.tracts import _tract_summary, get_observations
from forestds.api.schemas import EffectiveAreaPut
from forestds.db import reader, schema, writer
from forestds.db.models import Tract
from forestds.effective_area import (
    EffectiveAreaConflict,
    EffectiveAreaService,
    EffectiveAreaValidationError,
)
from forestds.export.formats import export_tract_to_file
from forestds.report.metrics import compute_report


TRACT_PK = "tract-effective"
BOUNDARY = Polygon(
    [
        (113.0, 22.0),
        (113.01, 22.0),
        (113.01, 22.01),
        (113.0, 22.01),
        (113.0, 22.0),
    ]
)


@pytest.fixture
def effective_db(tmp_path: Path) -> str:
    db_file = tmp_path / "effective-area.db"
    db_url = f"sqlite:///{db_file}"
    schema.init_db(db_url)
    conn = sqlite3.connect(db_file)
    conn.execute(
        "INSERT INTO tracts "
        "(tract_pk, region_id, city, county, tract_id, boundary_geom, effective_source, "
        "coverage_status, created_at, updated_at) "
        "VALUES (?, '440000', '深圳市', '宝安区', 'Q12', ?, 'manual', 'full', ?, ?)",
        (TRACT_PK, BOUNDARY.wkt, "2026-07-18T00:00:00+00:00", "2026-07-18T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()
    return db_url


@pytest.fixture
def service(effective_db: str) -> EffectiveAreaService:
    return EffectiveAreaService(effective_db)


def _geodesic_hm2(geometry: Polygon | MultiPolygon) -> float:
    polygons = [geometry] if isinstance(geometry, Polygon) else list(geometry.geoms)
    return sum(
        abs(Geod(ellps="WGS84").geometry_area_perimeter(orient(polygon, sign=1.0))[0])
        for polygon in polygons
    ) / 10_000.0


def _polygon(*coords: tuple[float, float]) -> dict:
    return mapping(Polygon(coords))


def test_effective_area_final_schema_is_consistent(effective_db: str) -> None:
    conn = sqlite3.connect(schema.resolve_db_path(effective_db))
    columns = {row[1]: row for row in conn.execute("PRAGMA table_info(tracts)")}
    conn.close()

    assert "effective_area_hm2" in columns
    assert columns["effective_area_hm2"][2].upper() == "REAL"
    assert Tract.__table__.columns["effective_area_hm2"].nullable is True

    postgis = (Path(__file__).parents[1] / "deploy/postgis/schema.sql").read_text(encoding="utf-8")
    assert "effective_geom      geometry(MultiPolygon, 4326)" in postgis
    assert "effective_area_hm2 DOUBLE PRECISION" in postgis
    assert "idx_tracts_effective_geom" in postgis


def test_effective_area_defaults_to_boundary(service: EffectiveAreaService) -> None:
    result = service.get(TRACT_PK)

    assert shape(result.geometry).equals(BOUNDARY)
    assert shape(result.boundary_geometry).equals(BOUNDARY)
    assert result.is_default is True
    assert result.effective_area_hm2 == pytest.approx(_geodesic_hm2(BOUNDARY), rel=1e-9)
    assert result.tract_area_hm2 == pytest.approx(_geodesic_hm2(BOUNDARY), rel=1e-9)
    assert result.effective_ratio == pytest.approx(1.0)


def test_save_accepts_polygon_holes_and_multiple_islands(
    service: EffectiveAreaService,
    effective_db: str,
) -> None:
    first = Polygon(
        [(113.001, 22.001), (113.005, 22.001), (113.005, 22.005), (113.001, 22.005)],
        holes=[
            [(113.002, 22.002), (113.003, 22.002), (113.003, 22.003), (113.002, 22.003)]
        ],
    )
    second = Polygon(
        [(113.006, 22.006), (113.009, 22.006), (113.009, 22.009), (113.006, 22.009)]
    )
    geometry = MultiPolygon([first, second])
    before = service.get(TRACT_PK)

    result = service.save(TRACT_PK, mapping(geometry), before.updated_at)

    assert shape(result.geometry).equals(geometry)
    assert result.is_default is False
    assert result.effective_area_hm2 == pytest.approx(_geodesic_hm2(geometry), rel=1e-9)
    assert result.updated_at != before.updated_at

    conn = sqlite3.connect(schema.resolve_db_path(effective_db))
    row = conn.execute(
        "SELECT effective_geom, effective_area_hm2 FROM tracts WHERE tract_pk=?",
        (TRACT_PK,),
    ).fetchone()
    conn.close()
    assert load_wkt(row[0]).equals(geometry)
    assert row[1] == pytest.approx(result.effective_area_hm2)


def test_save_rejects_stale_or_outside_geometry(service: EffectiveAreaService) -> None:
    with pytest.raises(EffectiveAreaConflict) as stale:
        service.save(TRACT_PK, mapping(BOUNDARY), "stale")
    assert stale.value.code == "effective_area_conflict"

    outside = _polygon(
        (112.999, 22.001),
        (113.002, 22.001),
        (113.002, 22.004),
        (112.999, 22.004),
        (112.999, 22.001),
    )
    current = service.get(TRACT_PK)
    res = service.save(TRACT_PK, outside, current.updated_at)
    assert res.effective_area_hm2 > 0


def test_outside_geometry_is_clipped_only_after_explicit_confirmation(
    service: EffectiveAreaService,
) -> None:
    outside = _polygon(
        (112.999, 22.001),
        (113.004, 22.001),
        (113.004, 22.004),
        (112.999, 22.004),
        (112.999, 22.001),
    )
    current = service.get(TRACT_PK)

    result = service.save(
        TRACT_PK,
        outside,
        current.updated_at,
        clip_to_boundary=True,
    )

    assert BOUNDARY.covers(shape(result.geometry))
    assert any("裁剪" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    ("geometry", "code"),
    [
        ({"type": "Polygon", "coordinates": []}, "empty_geometry"),
        (
            _polygon(
                (113.001, 22.001),
                (113.005, 22.001),
                (113.005, 22.001),
                (113.005, 22.005),
                (113.001, 22.001),
            ),
            "duplicate_vertex",
        ),
        ({"type": "Point", "coordinates": [113.001, 22.001]}, "non_polygon_geometry"),
    ],
)
def test_save_rejects_invalid_geometry(
    service: EffectiveAreaService,
    geometry: dict,
    code: str,
) -> None:
    current = service.get(TRACT_PK)
    with pytest.raises(EffectiveAreaValidationError) as invalid:
        service.save(TRACT_PK, geometry, current.updated_at)
    assert invalid.value.code == code


def test_save_auto_repairs_self_intersecting_geometry(service: EffectiveAreaService) -> None:
    geometry = _polygon(
        (113.001, 22.001),
        (113.009, 22.009),
        (113.009, 22.001),
        (113.001, 22.009),
        (113.001, 22.001),
    )
    current = service.get(TRACT_PK)
    result = service.save(TRACT_PK, geometry, current.updated_at)
    assert result.is_default is False
    assert result.effective_area_hm2 > 0


def test_save_rejects_non_wgs84_geojson_crs(service: EffectiveAreaService) -> None:
    geometry = mapping(BOUNDARY)
    geometry["crs"] = {"type": "name", "properties": {"name": "EPSG:3857"}}

    with pytest.raises(EffectiveAreaValidationError) as invalid:
        service.save(TRACT_PK, geometry, service.get(TRACT_PK).updated_at)

    assert invalid.value.code == "unsupported_crs"


def test_effective_area_api_maps_conflict_and_validation_errors(effective_db: str) -> None:
    current = get_effective_area(TRACT_PK, db_url=effective_db)
    assert current.is_default is True

    with pytest.raises(HTTPException) as stale:
        put_effective_area(
            TRACT_PK,
            EffectiveAreaPut(geometry=mapping(BOUNDARY), updated_at="stale"),
            db_url=effective_db,
        )
    assert stale.value.status_code == 409
    assert stale.value.detail["code"] == "effective_area_conflict"

    with pytest.raises(HTTPException) as invalid:
        put_effective_area(
            TRACT_PK,
            EffectiveAreaPut(
                geometry={"type": "Point", "coordinates": [113, 22]},
                updated_at=current.updated_at,
            ),
            db_url=effective_db,
        )
    assert invalid.value.status_code == 422
    assert invalid.value.detail["code"] == "non_polygon_geometry"


def _seed_active_observations(effective_db: str) -> str:
    conn = sqlite3.connect(schema.resolve_db_path(effective_db))
    conn.execute(
        "INSERT INTO tract_phases "
        "(tract_phase_pk, tract_pk, region_id, tract_id, phase_id, updated_at) "
        "VALUES ('phase-effective', ?, '440000', 'Q12', '20260718', '2026-07-18')",
        (TRACT_PK,),
    )
    conn.execute(
        "INSERT INTO tiffs "
        "(tiff_id, phase_id, tract_phase_pk, file_name, footprint_geom, crs_epsg, "
        "footprint_area_hm2, area_hm2, created_at, updated_at) "
        "VALUES ('tif01', '20260718', 'phase-effective', 'Q12.tif', ?, 4326, 100, 100, 'created', 'updated')",
        (BOUNDARY.wkt,),
    )
    conn.execute(
        "INSERT INTO runs "
        "(run_id, parent_run_id, tract_phase_pk, tiff_id, phase_id, task_type, status, "
        "metrics_json, started_at, created_at) "
        "VALUES ('run001', NULL, 'phase-effective', 'tif01', '20260718', 'infer', 'succeeded', ?, 'started', 'created')",
        (json.dumps({"canopy_cover_rate": 0.8, "canopy_cover_status": "ready"}),),
    )
    rows = [
        ("inside", "POINT (113.002 22.005)"),
        ("outside", "POINT (113.008 22.005)"),
    ]
    for observation_id, center in rows:
        conn.execute(
            "INSERT INTO tree_observations "
            "(observation_id, run_id, tract_phase_pk, tiff_id, phase_id, species, confidence, "
            "center_geom, crown_geom, crown_area_geo_real, created_at) "
            "VALUES (?, 'run001', 'phase-effective', 'tif01', '20260718', 'tree', 0.9, ?, "
            "'POLYGON ((113.001 22.004, 113.003 22.004, 113.003 22.006, 113.001 22.006, 113.001 22.004))', "
            "10, 'created')",
            (observation_id, center),
        )
    conn.execute(
        "UPDATE tiffs SET active_run_id='run001' WHERE tiff_id='tif01' AND phase_id='20260718'"
    )
    conn.commit()
    conn.close()
    return "run001"


def _save_left_half(service: EffectiveAreaService):
    left = box(113.0, 22.0, 113.005, 22.01)
    return service.save(TRACT_PK, mapping(left), service.get(TRACT_PK).updated_at)


def test_writer_initializes_exact_effective_area_for_new_boundary(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'writer-area.db'}"
    schema.init_db(db_url)

    conn = sqlite3.connect(schema.resolve_db_path(db_url))
    conn.execute(
        "INSERT INTO tracts (tract_pk, region_id, tract_id, effective_source, coverage_status, created_at, updated_at) "
        "VALUES ('440000_Q14', '440000', 'Q14', 'default', 'full', '2026-07-18', '2026-07-18')"
    )
    conn.execute(
        "INSERT INTO tract_phases (tract_phase_pk, tract_pk, region_id, tract_id, phase_id, updated_at) "
        "VALUES ('phase1', '440000_Q14', '440000', 'Q14', '20260718', '2026-07-18')"
    )
    conn.execute(
        "INSERT INTO tiffs (tiff_id, phase_id, tract_phase_pk, footprint_geom, footprint_bbox, area_hm2, created_at, updated_at) "
        "VALUES ('tf001', '20260718', 'phase1', ?, '[113.0, 22.0, 113.01, 22.01]', 12.5, '2026-07-18', '2026-07-18')",
        (BOUNDARY.wkt,)
    )
    writer.update_tract_geom_from_tiffs(conn, "440000_Q14")
    conn.commit()

    area = conn.execute("SELECT effective_area_hm2 FROM tracts WHERE tract_id='Q14'").fetchone()[0]
    conn.close()
    assert area == 12.5


def test_current_effective_area_filters_map_statistics_and_report(
    service: EffectiveAreaService,
    effective_db: str,
) -> None:
    _seed_active_observations(effective_db)
    saved = _save_left_half(service)

    rows = reader.fetch_observations(tract_id=TRACT_PK, url=effective_db)
    assert [row["observation_id"] for row in rows] == ["inside"]

    response = get_observations(TRACT_PK, run_id=None, geometry="point", db_url=effective_db)
    payload = json.loads(response.body)
    assert [feature["properties"]["id"] for feature in payload["features"]] == ["inside"]

    summary = _tract_summary(TRACT_PK, effective_db)
    assert summary["tree_count"] == 1
    assert summary["density_per_ha"] == pytest.approx(1 / saved.effective_area_hm2)
    assert summary["meta"]["area_m2"] == pytest.approx(saved.effective_area_hm2 * 10_000)
    assert summary["meta"]["area_source"] == "effective_area"

    report = compute_report(rows, tract=reader.get_tract(TRACT_PK, url=effective_db))
    assert report.density_per_ha == pytest.approx(1 / saved.effective_area_hm2)


def test_empty_tract_summary_still_reports_current_effective_area(
    service: EffectiveAreaService,
    effective_db: str,
) -> None:
    saved = _save_left_half(service)

    summary = _tract_summary(TRACT_PK, effective_db)

    assert summary["tree_count"] == 0
    assert summary["meta"]["area_m2"] == pytest.approx(saved.effective_area_hm2 * 10_000)
    assert summary["meta"]["area_source"] == "effective_area"


@pytest.mark.parametrize("crs_epsg", [None, 999999])
def test_map_filter_conservatively_keeps_observation_when_tiff_crs_is_unreliable(
    service: EffectiveAreaService,
    effective_db: str,
    crs_epsg: int | None,
) -> None:
    _seed_active_observations(effective_db)
    _save_left_half(service)
    conn = sqlite3.connect(schema.resolve_db_path(effective_db))
    conn.execute("DELETE FROM tree_observations WHERE observation_id='outside'")
    conn.execute(
        "UPDATE tree_observations SET center_geom='POINT (500000 2500000)' "
        "WHERE observation_id='inside'"
    )
    conn.execute(
        "UPDATE tiffs SET crs_epsg=?, crs_wkt=NULL WHERE tiff_id='tif01'",
        (crs_epsg,),
    )
    conn.commit()
    conn.close()

    rows = reader.fetch_observations(tract_id=TRACT_PK, url=effective_db)

    assert [row["observation_id"] for row in rows] == ["inside"]


def test_map_filter_reprojects_observation_centers_to_wgs84(
    service: EffectiveAreaService,
    effective_db: str,
) -> None:
    _seed_active_observations(effective_db)
    _save_left_half(service)
    project = Transformer.from_crs(4326, 3857, always_xy=True)
    conn = sqlite3.connect(schema.resolve_db_path(effective_db))
    for observation_id, point in (
        ("inside", project.transform(113.002, 22.005)),
        ("outside", project.transform(113.008, 22.005)),
    ):
        conn.execute(
            "UPDATE tree_observations SET center_geom=? WHERE observation_id=?",
            (f"POINT ({point[0]} {point[1]})", observation_id),
        )
    conn.execute("UPDATE tiffs SET crs_epsg=3857, crs_wkt=NULL WHERE tiff_id='tif01'")
    conn.commit()
    conn.close()

    rows = reader.fetch_observations(tract_id=TRACT_PK, url=effective_db)

    assert [row["observation_id"] for row in rows] == ["inside"]


def test_save_marks_active_canopy_metrics_pending(
    service: EffectiveAreaService,
    effective_db: str,
) -> None:
    _seed_active_observations(effective_db)

    _save_left_half(service)

    conn = sqlite3.connect(schema.resolve_db_path(effective_db))
    metrics = json.loads(conn.execute("SELECT metrics_json FROM runs WHERE run_id='run001'").fetchone()[0])
    conn.close()
    assert metrics["canopy_cover_status"] == "pending"
    assert "canopy_cover_rate" not in metrics


def test_existing_export_can_include_effective_area_and_run_provenance(
    service: EffectiveAreaService,
    effective_db: str,
    tmp_path: Path,
) -> None:
    run_id = _seed_active_observations(effective_db)
    saved = _save_left_half(service)

    result = export_tract_to_file(
        tract_id=TRACT_PK,
        run_id=run_id,
        fmt="geojson",
        out_path=tmp_path / "effective.geojson",
        db_url=effective_db,
        include_effective_area=True,
    )

    payload = json.loads(Path(result["out_path"]).read_text(encoding="utf-8"))
    layers = {feature["properties"]["layer"] for feature in payload["features"]}
    assert layers == {"observations", "effective_area"}
    observation = next(f for f in payload["features"] if f["properties"]["layer"] == "observations")
    assert observation["properties"]["run_id"] == run_id
    assert observation["properties"]["task_type"] == "infer"
    assert observation["properties"]["parent_run_id"] is None
    effective = next(f for f in payload["features"] if f["properties"]["layer"] == "effective_area")
    assert shape(effective["geometry"]).equals(shape(saved.geometry))
    assert effective["properties"]["effective_area_hm2"] == pytest.approx(saved.effective_area_hm2)

    without = export_tract_to_file(
        tract_id=TRACT_PK,
        run_id=run_id,
        fmt="geojson",
        out_path=tmp_path / "observations-only.geojson",
        db_url=effective_db,
        include_effective_area=False,
    )
    without_payload = json.loads(Path(without["out_path"]).read_text(encoding="utf-8"))
    assert {feature["properties"]["layer"] for feature in without_payload["features"]} == {"observations"}


def test_gpkg_and_shapefile_exports_add_effective_area_sibling_layer(
    service: EffectiveAreaService,
    effective_db: str,
    tmp_path: Path,
) -> None:
    _seed_active_observations(effective_db)
    _save_left_half(service)

    gpkg = export_tract_to_file(
        tract_id=TRACT_PK,
        run_id="run001",
        fmt="gpkg",
        out_path=tmp_path / "effective.gpkg",
        db_url=effective_db,
        include_effective_area=True,
    )
    import pyogrio

    assert set(pyogrio.list_layers(gpkg["out_path"])[:, 0]) == {"observations", "effective_area"}
    observations = pyogrio.read_dataframe(gpkg["out_path"], layer="observations")
    assert observations.iloc[0]["task_type"] == "infer"
    assert observations.iloc[0]["tiff_id"] == "tif01"

    shapefile = export_tract_to_file(
        tract_id=TRACT_PK,
        run_id="run001",
        fmt="shp",
        out_path=tmp_path / "effective.zip",
        db_url=effective_db,
        include_effective_area=True,
    )
    assert Path(shapefile["out_path"]).suffix == ".zip"
    with zipfile.ZipFile(shapefile["out_path"]) as archive:
        names = set(archive.namelist())
    assert "observations.shp" in names
    assert "effective_area.shp" in names


def test_csv_export_keeps_run_provenance_columns(
    service: EffectiveAreaService,
    effective_db: str,
    tmp_path: Path,
) -> None:
    _seed_active_observations(effective_db)
    _save_left_half(service)

    result = export_tract_to_file(
        tract_id=TRACT_PK,
        run_id="run001",
        fmt="csv",
        out_path=tmp_path / "effective.csv",
        db_url=effective_db,
        include_effective_area=True,
    )

    header = Path(result["out_path"]).read_text(encoding="utf-8").splitlines()[0]
    assert "task_type" in header
    assert "parent_run_id" in header
    assert "tiff_id" in header
    assert "phase_id" in header


def test_manual_effective_area_recalculates_tiff_intersection_area(
    service: EffectiveAreaService,
    effective_db: str,
) -> None:
    _seed_active_observations(effective_db)
    _save_left_half(service)

    conn = sqlite3.connect(schema.resolve_db_path(effective_db))
    native_area = conn.execute("SELECT area_hm2 FROM tiffs WHERE tiff_id='tif01'").fetchone()[0]
    effective_area = conn.execute("SELECT effective_area_hm2 FROM tiffs WHERE tiff_id='tif01'").fetchone()[0]
    tract_source = conn.execute("SELECT effective_source FROM tracts WHERE tract_pk=?", (TRACT_PK,)).fetchone()[0]
    conn.close()

    assert tract_source == "manual"
    assert native_area == 100.0
    assert effective_area is not None
    assert 0.0 < effective_area < 100.0
