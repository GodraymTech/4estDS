from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import geopandas as gpd
import pytest
from pyproj import Transformer
from shapely.geometry import LineString, Polygon, mapping, shape

from forestds.db import schema
from forestds.effective_area import EffectiveAreaImportError, EffectiveAreaService, ImportFile


TRACT_PK = "tract-import"
BOUNDARY = Polygon([(113.0, 22.0), (113.02, 22.0), (113.02, 22.02), (113.0, 22.02)])
IMPORTED = Polygon([(113.002, 22.002), (113.01, 22.002), (113.01, 22.01), (113.002, 22.01)])


@pytest.fixture
def import_service(tmp_path: Path) -> EffectiveAreaService:
    db_file = tmp_path / "imports.db"
    db_url = f"sqlite:///{db_file}"
    schema.init_db(db_url)
    conn = sqlite3.connect(db_file)
    conn.execute(
        "INSERT INTO tracts "
        "(tract_pk, region_id, tract_id, boundary_geom, boundary_source, coverage_status, created_at, updated_at) "
        "VALUES (?, '440000', 'Q13', ?, 'manual', 'full', '2026-07-18', '2026-07-18')",
        (TRACT_PK, BOUNDARY.wkt),
    )
    conn.commit()
    conn.close()
    return EffectiveAreaService(db_url)


def _write_geojson(path: Path, geometry: Polygon, *, crs: str | None = None) -> None:
    payload: dict = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {}, "geometry": mapping(geometry)}],
    }
    if crs:
        payload["crs"] = {"type": "name", "properties": {"name": crs}}
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_shapefile(path: Path) -> list[Path]:
    gpd.GeoDataFrame({"name": ["area"]}, geometry=[IMPORTED], crs="EPSG:4326").to_file(
        path,
        driver="ESRI Shapefile",
    )
    return sorted(path.parent.glob(path.stem + ".*"))


@pytest.mark.parametrize("suffix", [".geojson", ".json"])
def test_inspect_geojson_and_json(import_service: EffectiveAreaService, tmp_path: Path, suffix: str) -> None:
    source = tmp_path / f"effective{suffix}"
    _write_geojson(source, IMPORTED)

    result = import_service.inspect_import(TRACT_PK, source)

    assert shape(result.geometry).equals(IMPORTED)
    assert result.source_crs == "EPSG:4326"
    assert result.feature_count == 1
    assert result.layer is None
    assert result.requires_clip is False


def test_inspect_reprojects_explicit_geojson_crs(import_service: EffectiveAreaService, tmp_path: Path) -> None:
    project = Transformer.from_crs(4326, 3857, always_xy=True).transform
    projected = Polygon([project(x, y) for x, y in IMPORTED.exterior.coords])
    source = tmp_path / "projected.geojson"
    _write_geojson(source, projected, crs="EPSG:3857")

    result = import_service.inspect_import(TRACT_PK, source)

    assert shape(result.geometry).hausdorff_distance(IMPORTED) < 1e-8
    assert result.source_crs == "EPSG:3857"
    assert result.target_crs == "EPSG:4326"


def test_inspect_local_sibling_zip_and_browser_multifile_shapefile(
    import_service: EffectiveAreaService,
    tmp_path: Path,
) -> None:
    shp = tmp_path / "effective.shp"
    siblings = _write_shapefile(shp)

    local = import_service.inspect_import(TRACT_PK, shp)
    assert shape(local.geometry).equals(IMPORTED)

    archive = tmp_path / "effective.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for sibling in siblings:
            zf.write(sibling, sibling.name)
    zipped = import_service.inspect_import(TRACT_PK, archive)
    assert shape(zipped.geometry).equals(IMPORTED)

    browser_files = [ImportFile(item.name, item.read_bytes()) for item in siblings]
    browser = import_service.inspect_import(TRACT_PK, browser_files)
    assert shape(browser.geometry).equals(IMPORTED)


@pytest.mark.parametrize("missing", [".dbf", ".shx", ".prj"])
def test_inspect_shapefile_reports_each_missing_component(
    import_service: EffectiveAreaService,
    tmp_path: Path,
    missing: str,
) -> None:
    shp = tmp_path / "broken.shp"
    _write_shapefile(shp)
    (tmp_path / f"broken{missing}").unlink()

    with pytest.raises(EffectiveAreaImportError) as error:
        import_service.inspect_import(TRACT_PK, shp)

    expected_code = "missing_crs" if missing == ".prj" else "missing_shapefile_component"
    assert error.value.code == expected_code
    assert missing in str(error.value.details)


def test_inspect_gpkg_requires_explicit_layer_when_multiple_exist(
    import_service: EffectiveAreaService,
    tmp_path: Path,
) -> None:
    source = tmp_path / "areas.gpkg"
    first = gpd.GeoDataFrame({"name": ["a"]}, geometry=[IMPORTED], crs="EPSG:4326")
    second_geom = Polygon([(113.011, 22.011), (113.015, 22.011), (113.015, 22.015), (113.011, 22.015)])
    second = gpd.GeoDataFrame({"name": ["b"]}, geometry=[second_geom], crs="EPSG:4326")
    first.to_file(source, layer="first", driver="GPKG")
    second.to_file(source, layer="second", driver="GPKG", mode="a")

    with pytest.raises(EffectiveAreaImportError) as error:
        import_service.inspect_import(TRACT_PK, source)
    assert error.value.code == "multiple_layers"
    assert set(error.value.details["layers"]) == {"first", "second"}

    selected = import_service.inspect_import(TRACT_PK, source, layer="second")
    assert selected.layer == "second"
    assert set(selected.layers) == {"first", "second"}
    assert shape(selected.geometry).equals(second_geom)


@pytest.mark.parametrize(
    ("suffix", "driver"),
    [(".kml", "KML"), (".fgb", "FlatGeobuf")],
)
def test_inspect_kml_and_flatgeobuf(
    import_service: EffectiveAreaService,
    tmp_path: Path,
    suffix: str,
    driver: str,
) -> None:
    source = tmp_path / f"effective{suffix}"
    gpd.GeoDataFrame({"name": ["area"]}, geometry=[IMPORTED], crs="EPSG:4326").to_file(
        source,
        driver=driver,
    )

    result = import_service.inspect_import(TRACT_PK, source)

    assert shape(result.geometry).equals(IMPORTED)


def test_inspect_rejects_missing_crs_non_polygon_and_unsupported_format(
    import_service: EffectiveAreaService,
    tmp_path: Path,
) -> None:
    no_crs = tmp_path / "no-crs.fgb"
    gpd.GeoDataFrame({"name": ["area"]}, geometry=[IMPORTED]).to_file(no_crs, driver="FlatGeobuf")
    with pytest.raises(EffectiveAreaImportError) as crs_error:
        import_service.inspect_import(TRACT_PK, no_crs)
    assert crs_error.value.code == "missing_crs"

    lines = tmp_path / "lines.geojson"
    lines.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {}, "geometry": mapping(LineString([(113, 22), (113.01, 22.01)]))}
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(EffectiveAreaImportError) as geometry_error:
        import_service.inspect_import(TRACT_PK, lines)
    assert geometry_error.value.code == "no_polygon_features"

    unsupported = tmp_path / "effective.txt"
    unsupported.write_text("not gis", encoding="utf-8")
    with pytest.raises(EffectiveAreaImportError) as format_error:
        import_service.inspect_import(TRACT_PK, unsupported)
    assert format_error.value.code == "unsupported_format"
