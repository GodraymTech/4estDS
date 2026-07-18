"""GIS 文件导入预检，统一输出 EPSG:4326 面几何。"""
from __future__ import annotations

import json
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from pyproj import CRS, Transformer
from shapely import transform as transform_geometry
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


@dataclass(frozen=True)
class ImportFile:
    name: str
    content: bytes


@dataclass(frozen=True)
class ImportedVector:
    geometry: BaseGeometry
    source_crs: str
    feature_count: int
    polygon_count: int
    layer: str | None
    layers: tuple[str, ...]
    warnings: tuple[str, ...] = ()


_SUPPORTED = {".geojson", ".json", ".shp", ".zip", ".gpkg", ".kml", ".fgb"}
_SHAPE_REQUIRED = {".shp", ".dbf", ".shx", ".prj"}


def _error(message: str, *, code: str, details: Mapping[str, Any] | None = None):
    from .service import EffectiveAreaImportError

    raise EffectiveAreaImportError(message, code=code, details=details)


def _canonical_crs(crs: CRS | str) -> str:
    value = CRS.from_user_input(crs)
    authority = value.to_authority()
    return f"{authority[0]}:{authority[1]}" if authority else value.to_string()


def _polygon_parts(geometry: BaseGeometry) -> list[Polygon]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        out: list[Polygon] = []
        for item in geometry.geoms:
            out.extend(_polygon_parts(item))
        return out
    return []


def _merge_features(
    geometries: Iterable[BaseGeometry],
    *,
    source_crs: str,
    feature_count: int,
    layer: str | None,
    layers: tuple[str, ...],
) -> ImportedVector:
    polygons: list[Polygon] = []
    non_polygon_count = 0
    for geometry in geometries:
        parts = _polygon_parts(geometry)
        if parts:
            polygons.extend(parts)
        elif not geometry.is_empty:
            non_polygon_count += 1
    if not polygons:
        _error(
            "导入文件不包含面要素。",
            code="no_polygon_features",
            details={"feature_count": feature_count},
        )
    merged = unary_union(polygons)
    warnings: tuple[str, ...] = ()
    if non_polygon_count:
        warnings = (f"已忽略 {non_polygon_count} 个非面要素。",)
    return ImportedVector(
        geometry=merged,
        source_crs=source_crs,
        feature_count=feature_count,
        polygon_count=len(polygons),
        layer=layer,
        layers=layers,
        warnings=warnings,
    )


def _reproject(vector: ImportedVector) -> ImportedVector:
    source = CRS.from_user_input(vector.source_crs)
    if source.to_epsg() == 4326:
        return vector
    transformer = Transformer.from_crs(source, 4326, always_xy=True)
    converted = transform_geometry(vector.geometry, transformer.transform, interleaved=False)
    return ImportedVector(
        geometry=converted,
        source_crs=vector.source_crs,
        feature_count=vector.feature_count,
        polygon_count=vector.polygon_count,
        layer=vector.layer,
        layers=vector.layers,
        warnings=vector.warnings,
    )


def _geojson_crs(payload: Mapping[str, Any]) -> str:
    raw = payload.get("crs")
    if raw is None:
        return "EPSG:4326"
    try:
        name = raw["properties"]["name"]
        return _canonical_crs(str(name))
    except Exception as exc:  # noqa: BLE001
        _error("GeoJSON CRS 无法识别。", code="missing_crs")
        raise AssertionError from exc


def _read_geojson(path: Path) -> ImportedVector:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        _error("GeoJSON/JSON 文件无法解析。", code="invalid_file", details={"error": str(exc)})
    if not isinstance(payload, Mapping):
        _error("GeoJSON 顶层必须是对象。", code="invalid_file")
    source_crs = _geojson_crs(payload)
    payload_type = payload.get("type")
    raw_geometries: list[Mapping[str, Any]] = []
    if payload_type == "FeatureCollection":
        features = payload.get("features") or []
        raw_geometries = [item.get("geometry") for item in features if isinstance(item, Mapping) and item.get("geometry")]
        feature_count = len(features)
    elif payload_type == "Feature":
        raw_geometries = [payload.get("geometry")] if payload.get("geometry") else []
        feature_count = 1
    else:
        raw_geometries = [payload]
        feature_count = 1
    try:
        geometries = [shape(item) for item in raw_geometries]
    except Exception as exc:  # noqa: BLE001
        _error("GeoJSON 几何无法解析。", code="invalid_geometry", details={"error": str(exc)})
    vector = _merge_features(
        geometries,
        source_crs=source_crs,
        feature_count=feature_count,
        layer=None,
        layers=(),
    )
    return _reproject(vector)


def _casefold_siblings(path: Path) -> dict[str, Path]:
    return {item.suffix.lower(): item for item in path.parent.iterdir() if item.stem.casefold() == path.stem.casefold()}


def _validate_shapefile(path: Path) -> None:
    siblings = _casefold_siblings(path)
    missing = sorted(_SHAPE_REQUIRED - set(siblings))
    if not missing:
        return
    if missing == [".prj"]:
        _error(
            "Shapefile 缺少 .prj，无法确定 CRS。",
            code="missing_crs",
            details={"missing": missing},
        )
    _error(
        "Shapefile 配套文件不完整。",
        code="missing_shapefile_component",
        details={"missing": missing},
    )


def _vector_layers(path: Path) -> tuple[str, ...]:
    try:
        import pyogrio

        values = pyogrio.list_layers(path)
        return tuple(str(row[0]) for row in values)
    except Exception as exc:  # noqa: BLE001
        _error("无法读取 GIS 图层列表。", code="invalid_file", details={"error": str(exc)})
    return ()


def _read_ogr(path: Path, *, layer: str | None) -> ImportedVector:
    if path.suffix.lower() == ".shp":
        _validate_shapefile(path)
    layers = _vector_layers(path)
    if layer and layers and layer not in layers:
        _error(
            "指定图层不存在。",
            code="layer_not_found",
            details={"layer": layer, "layers": list(layers)},
        )
    if len(layers) > 1 and layer is None:
        _error(
            "文件包含多个图层，请明确选择。",
            code="multiple_layers",
            details={"layers": list(layers)},
        )
    selected = layer or (layers[0] if len(layers) == 1 else None)
    try:
        import pyogrio

        frame = pyogrio.read_dataframe(path, layer=selected)
    except Exception as exc:  # noqa: BLE001
        _error("GIS 文件读取失败。", code="invalid_file", details={"error": str(exc)})
    if frame.crs is None:
        _error("GIS 文件缺少 CRS。", code="missing_crs")
    source_crs = _canonical_crs(frame.crs)
    geometries = [geometry for geometry in frame.geometry if geometry is not None]
    vector = _merge_features(
        geometries,
        source_crs=source_crs,
        feature_count=len(frame),
        layer=selected if len(layers) > 1 or layer else None,
        layers=layers,
    )
    return _reproject(vector)


def _safe_extract_shapefile(archive: Path, directory: Path) -> Path:
    try:
        with zipfile.ZipFile(archive) as zf:
            files = [item for item in zf.infolist() if not item.is_dir()]
            shp_files = [item for item in files if Path(item.filename).suffix.lower() == ".shp"]
            if len(shp_files) != 1:
                _error(
                    "Shapefile ZIP 必须且只能包含一个 .shp。",
                    code="invalid_shapefile_archive",
                    details={"shp_count": len(shp_files)},
                )
            stem = Path(shp_files[0].filename).stem.casefold()
            matched = [item for item in files if Path(item.filename).stem.casefold() == stem]
            present = {Path(item.filename).suffix.lower() for item in matched}
            missing = sorted(_SHAPE_REQUIRED - present)
            if missing:
                code = "missing_crs" if missing == [".prj"] else "missing_shapefile_component"
                _error("Shapefile ZIP 配套文件不完整。", code=code, details={"missing": missing})
            for item in matched:
                target = directory / Path(item.filename).name
                target.write_bytes(zf.read(item))
    except zipfile.BadZipFile as exc:
        _error("ZIP 文件损坏。", code="invalid_file", details={"error": str(exc)})
    return directory / (Path(shp_files[0].filename).stem + ".shp")


def _inspect_path(path: Path, *, layer: str | None) -> ImportedVector:
    if not path.exists() or not path.is_file():
        _error("导入文件不存在。", code="file_not_found", details={"path": str(path)})
    suffix = path.suffix.lower()
    if suffix not in _SUPPORTED:
        _error("不支持的 GIS 文件格式。", code="unsupported_format", details={"suffix": suffix})
    if suffix in {".geojson", ".json"}:
        return _read_geojson(path)
    if suffix == ".zip":
        with tempfile.TemporaryDirectory(prefix="forestds-effective-area-") as tmp:
            shp = _safe_extract_shapefile(path, Path(tmp))
            return _read_ogr(shp, layer=layer)
    return _read_ogr(path, layer=layer)


def _materialize_files(files: Sequence[ImportFile], directory: Path) -> Path:
    if not files:
        _error("未提供导入文件。", code="empty_upload")
    names = [Path(item.name).name for item in files]
    if len(set(name.casefold() for name in names)) != len(names):
        _error("上传文件存在重名。", code="duplicate_upload_name")
    for item, name in zip(files, names):
        (directory / name).write_bytes(item.content)
    primary = [directory / name for name in names if Path(name).suffix.lower() in _SUPPORTED]
    shp = [item for item in primary if item.suffix.lower() == ".shp"]
    if shp:
        if len(shp) != 1:
            _error("多文件 Shapefile 必须且只能选择一个 .shp。", code="invalid_shapefile_upload")
        return shp[0]
    if len(primary) != 1:
        _error("一次只能预检一个 GIS 数据源。", code="ambiguous_upload")
    return primary[0]


def inspect_vector_source(
    source: str | Path | Sequence[ImportFile],
    *,
    layer: str | None = None,
) -> ImportedVector:
    """读取本地路径或浏览器多文件上传，并统一转到 EPSG:4326。"""
    if isinstance(source, (str, Path)):
        return _inspect_path(Path(source).expanduser(), layer=layer)
    if not isinstance(source, Sequence) or isinstance(source, (bytes, bytearray)):
        _error("无效的导入源。", code="invalid_source")
    with tempfile.TemporaryDirectory(prefix="forestds-effective-area-") as tmp:
        path = _materialize_files(source, Path(tmp))
        return _inspect_path(path, layer=layer)

