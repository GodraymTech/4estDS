"""有效区域领域服务：规范化、验证、面积、并发保存与导入预检。"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from pyproj import CRS, Geod, Transformer
from shapely import transform as transform_geometry
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import orient
from shapely.validation import explain_validity, make_valid
from shapely.wkt import loads as load_wkt

from loguru import logger

from ..db.schema import resolve_db_path


class EffectiveAreaError(RuntimeError):
    """可映射到 HTTP 边界的有效区域领域异常。"""

    def __init__(self, message: str, *, code: str, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    def as_detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": self.details}


class EffectiveAreaNotFound(EffectiveAreaError):
    def __init__(self, tract_pk: str):
        super().__init__(f"地块不存在: {tract_pk}", code="tract_not_found", details={"tract_pk": tract_pk})


class EffectiveAreaConflict(EffectiveAreaError):
    pass


class EffectiveAreaValidationError(EffectiveAreaError):
    pass


class EffectiveAreaImportError(EffectiveAreaError):
    pass


@dataclass(frozen=True)
class EffectiveAreaResult:
    tract_pk: str
    boundary_geometry: dict[str, Any]
    geometry: dict[str, Any]
    tract_area_hm2: float
    tract_phase_area_hm2: float
    effective_area_hm2: float
    effective_ratio: float
    updated_at: str
    warnings: tuple[str, ...]
    is_default: bool


@dataclass(frozen=True)
class EffectiveAreaImportResult:
    tract_pk: str
    geometry: dict[str, Any]
    source_crs: str
    target_crs: str
    feature_count: int
    polygon_count: int
    layer: str | None
    layers: tuple[str, ...]
    effective_area_hm2: float
    effective_ratio: float
    requires_clip: bool
    warnings: tuple[str, ...]


def _connect(url: str | None) -> sqlite3.Connection:
    conn = sqlite3.connect(resolve_db_path(url), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _canonical_crs_name(crs: CRS | str) -> str:
    value = CRS.from_user_input(crs)
    authority = value.to_authority()
    return f"{authority[0]}:{authority[1]}" if authority else value.to_string()


def _declared_geojson_crs(value: Mapping[str, Any]) -> str | None:
    raw = value.get("crs")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        return "invalid"
    properties = raw.get("properties")
    if not isinstance(properties, Mapping):
        return "invalid"
    name = properties.get("name")
    return str(name) if name else "invalid"


def _iter_rings(value: Mapping[str, Any]):
    geometry_type = value.get("type")
    coordinates = value.get("coordinates")
    if geometry_type == "Polygon" and isinstance(coordinates, Sequence):
        yield from coordinates
    elif geometry_type == "MultiPolygon" and isinstance(coordinates, Sequence):
        for polygon in coordinates:
            if isinstance(polygon, Sequence):
                yield from polygon


def _has_duplicate_vertex(value: Mapping[str, Any]) -> bool:
    for ring in _iter_rings(value):
        if not isinstance(ring, Sequence) or len(ring) < 2:
            continue
        points: list[tuple[float, float]] = []
        try:
            points = [(float(point[0]), float(point[1])) for point in ring]
        except (TypeError, ValueError, IndexError):
            continue
        if len(points) > 1 and points[0] == points[-1]:
            points = points[:-1]
        if len(points) != len(set(points)):
            return True
    return False


def _as_multipolygon(geometry: BaseGeometry) -> MultiPolygon:
    if isinstance(geometry, Polygon):
        return MultiPolygon([geometry]).normalize()
    if isinstance(geometry, MultiPolygon):
        return geometry.normalize()
    if isinstance(geometry, GeometryCollection):
        polygons: list[Polygon] = []
        for item in geometry.geoms:
            if isinstance(item, Polygon):
                polygons.append(item)
            elif isinstance(item, MultiPolygon):
                polygons.extend(item.geoms)
        if polygons:
            return MultiPolygon(polygons).normalize()
    raise EffectiveAreaValidationError(
        "有效区域只支持 Polygon 或 MultiPolygon。",
        code="non_polygon_geometry",
    )


def _parse_geometry(value: Mapping[str, Any] | BaseGeometry) -> MultiPolygon:
    if isinstance(value, BaseGeometry):
        geometry = value
    else:
        if not isinstance(value, Mapping):
            raise EffectiveAreaValidationError("geometry 必须是 GeoJSON 对象。", code="invalid_geometry")
        declared_crs = _declared_geojson_crs(value)
        if declared_crs:
            try:
                crs = CRS.from_user_input(declared_crs)
            except Exception as exc:  # noqa: BLE001
                raise EffectiveAreaValidationError(
                    "GeoJSON CRS 无法识别。",
                    code="unsupported_crs",
                    details={"crs": declared_crs},
                ) from exc
            if crs.to_epsg() != 4326:
                raise EffectiveAreaValidationError(
                    "保存接口仅接受 EPSG:4326 GeoJSON；GIS 文件请先走导入预检。",
                    code="unsupported_crs",
                    details={"crs": declared_crs},
                )
        geometry_type = value.get("type")
        if geometry_type not in {"Polygon", "MultiPolygon"}:
            raise EffectiveAreaValidationError(
                "有效区域只支持 Polygon 或 MultiPolygon。",
                code="non_polygon_geometry",
                details={"geometry_type": geometry_type},
            )
        if _has_duplicate_vertex(value):
            raise EffectiveAreaValidationError("几何包含重复顶点。", code="duplicate_vertex")
        try:
            geometry = shape(value)
        except Exception as exc:  # noqa: BLE001
            raise EffectiveAreaValidationError("GeoJSON 几何无法解析。", code="invalid_geometry") from exc
    if geometry.is_empty:
        raise EffectiveAreaValidationError("有效区域不能为空。", code="empty_geometry")
    polygonal = _as_multipolygon(geometry)
    if not polygonal.is_valid:
        polygonal = _as_multipolygon(make_valid(polygonal))
        if not polygonal.is_valid:
            raise EffectiveAreaValidationError(
                "有效区域几何无效。",
                code="invalid_geometry",
                details={"reason": explain_validity(polygonal)},
            )
    if polygonal.area <= 0:
        raise EffectiveAreaValidationError("有效区域面积必须大于零。", code="zero_area")
    minx, miny, maxx, maxy = polygonal.bounds
    if minx < -180 or maxx > 180 or miny < -90 or maxy > 90:
        raise EffectiveAreaValidationError(
            "有效区域坐标超出 EPSG:4326 合法范围。",
            code="coordinate_out_of_range",
            details={"bounds": [minx, miny, maxx, maxy]},
        )
    return polygonal


_GEOD = Geod(ellps="WGS84")


def geodesic_area_hm2(geometry: BaseGeometry) -> float:
    """计算 EPSG:4326 Polygon/MultiPolygon 的椭球面积（hm²）。"""
    polygons = [geometry] if isinstance(geometry, Polygon) else list(_as_multipolygon(geometry).geoms)
    area_m2 = 0.0
    for polygon in polygons:
        # Geod 以环方向判定外环/洞；Shapely 拓扑本身不要求输入环方向，因此先显式定向。
        area, _ = _GEOD.geometry_area_perimeter(orient(polygon, sign=1.0))
        area_m2 += abs(float(area))
    return area_m2 / 10_000.0


def _local_transformers(geometry: BaseGeometry) -> tuple[Transformer, Transformer]:
    centroid = geometry.centroid
    zone = max(1, min(60, int((centroid.x + 180) // 6) + 1))
    epsg = (32600 if centroid.y >= 0 else 32700) + zone
    return (
        Transformer.from_crs(4326, epsg, always_xy=True),
        Transformer.from_crs(epsg, 4326, always_xy=True),
    )


def _project(geometry: BaseGeometry, transformer: Transformer) -> BaseGeometry:
    return transform_geometry(geometry, transformer.transform, interleaved=False)


class EffectiveAreaService:
    """每地块唯一当前有效区域的应用服务。"""

    def __init__(self, db_url: str | None = None, *, boundary_epsilon_m: float = 0.05):
        self.db_url = db_url
        self.boundary_epsilon_m = max(0.0, float(boundary_epsilon_m))

    def _row(self, tract_pk: str, *, conn: sqlite3.Connection | None = None) -> sqlite3.Row:
        owned = conn is None
        connection = conn or _connect(self.db_url)
        try:
            row = connection.execute(
                "SELECT tract_pk, boundary_geom, effective_geom, effective_area_hm2, updated_at "
                "FROM tracts WHERE tract_pk=?",
                (tract_pk,),
            ).fetchone()
        finally:
            if owned:
                connection.close()
        if row is None:
            raise EffectiveAreaNotFound(tract_pk)
        if not row["boundary_geom"]:
            raise EffectiveAreaValidationError(
                "地块缺少 boundary_geom，需先修复地块资产。",
                code="missing_boundary",
                details={"tract_pk": tract_pk},
            )
        return row

    @staticmethod
    def _boundary(row: sqlite3.Row) -> MultiPolygon:
        try:
            return _parse_geometry(load_wkt(row["boundary_geom"]))
        except EffectiveAreaValidationError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise EffectiveAreaValidationError(
                "地块 boundary_geom 无法解析。",
                code="invalid_boundary",
                details={"tract_pk": row["tract_pk"]},
            ) from exc

    def _result(
        self,
        row: sqlite3.Row,
        boundary: MultiPolygon,
        effective: MultiPolygon,
        *,
        conn: sqlite3.Connection | None = None,
        warnings: tuple[str, ...] = (),
        is_default: bool,
    ) -> EffectiveAreaResult:
        tract_area = geodesic_area_hm2(boundary)
        effective_area = geodesic_area_hm2(effective)
        c = conn or _connect(self.db_url)
        try:
            row_phase = c.execute(
                "SELECT tp.area_hm2 FROM tract_phases tp "
                "JOIN tiffs tf ON tf.tract_phase_pk = tp.tract_phase_pk "
                "WHERE tp.tract_pk=? GROUP BY tp.phase_id ORDER BY COUNT(tf.tiff_id) DESC, tp.phase_id DESC LIMIT 1",
                (row["tract_pk"],),
            ).fetchone()
            tract_phase_area = (row_phase[0] if row_phase and row_phase[0] is not None else 0.0)
        finally:
            if conn is None:
                c.close()

        return EffectiveAreaResult(
            tract_pk=row["tract_pk"],
            boundary_geometry=mapping(boundary),
            geometry=mapping(effective),
            tract_area_hm2=tract_area,
            tract_phase_area_hm2=round(float(tract_phase_area), 4),
            effective_area_hm2=effective_area,
            effective_ratio=(effective_area / tract_phase_area if tract_phase_area > 0 else (effective_area / tract_area if tract_area > 0 else 0.0)),
            updated_at=row["updated_at"],
            warnings=warnings,
            is_default=is_default,
        )

    def get(self, tract_pk: str) -> EffectiveAreaResult:
        row = self._row(tract_pk)
        boundary = self._boundary(row)
        is_default = not bool(row["effective_geom"])
        effective = boundary if is_default else _parse_geometry(load_wkt(row["effective_geom"]))
        return self._result(row, boundary, effective, is_default=is_default)

    def _within_boundary(self, geometry: MultiPolygon, boundary: MultiPolygon) -> bool:
        forward, _ = _local_transformers(boundary)
        projected_boundary = _project(boundary, forward)
        projected_geometry = _project(geometry, forward)
        return projected_boundary.buffer(self.boundary_epsilon_m).covers(projected_geometry)

    @staticmethod
    def _next_updated_at(previous: str) -> str:
        now = datetime.now(timezone.utc)
        try:
            old = datetime.fromisoformat(previous.replace("Z", "+00:00"))
            if old.tzinfo is None:
                old = old.replace(tzinfo=timezone.utc)
            if now <= old:
                now = old + timedelta(microseconds=1)
        except ValueError:
            pass
        return now.isoformat(timespec="microseconds")

    def save(
        self,
        tract_pk: str,
        geometry: Mapping[str, Any] | BaseGeometry,
        expected_updated_at: str,
        *,
        clip_to_boundary: bool = False,
    ) -> EffectiveAreaResult:
        candidate = _parse_geometry(geometry)
        conn = _connect(self.db_url)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = self._row(tract_pk, conn=conn)
            if row["updated_at"] != expected_updated_at:
                raise EffectiveAreaConflict(
                    "有效区域已被其他操作更新，请重新加载后再保存。",
                    code="effective_area_conflict",
                    details={"expected_updated_at": expected_updated_at, "actual_updated_at": row["updated_at"]},
                )
            boundary = self._boundary(row)
            warnings: tuple[str, ...] = ()
            if clip_to_boundary:
                candidate = _as_multipolygon(candidate.intersection(boundary))
                if candidate.is_empty or candidate.area <= 0:
                    raise EffectiveAreaValidationError(
                        "裁剪后有效区域为空。",
                        code="empty_after_clip",
                    )
                warnings = ("已按用户确认将有效区域裁剪到地块边界。",)

            is_default = candidate.equals(boundary)
            area_hm2 = geodesic_area_hm2(candidate)
            effective_source = "default" if is_default else "manual"
            updated_at = self._next_updated_at(row["updated_at"])
            cursor = conn.execute(
                "UPDATE tracts SET effective_geom=?, effective_area_hm2=?, effective_source=?, updated_at=? "
                "WHERE tract_pk=? AND updated_at=?",
                (None if is_default else candidate.wkt, area_hm2, effective_source, updated_at, tract_pk, expected_updated_at),
            )
            if cursor.rowcount != 1:
                raise EffectiveAreaConflict(
                    "有效区域已被其他操作更新，请重新加载后再保存。",
                    code="effective_area_conflict",
                )
            if is_default:
                from ..db.writer import update_tract_geom_from_tiffs
                update_tract_geom_from_tiffs(conn, tract_pk)
            else:
                _update_tiff_intersections_for_manual_tract(conn, tract_pk, candidate)
            active_runs = conn.execute(
                "SELECT DISTINCT r.run_id, r.metrics_json FROM runs r "
                "JOIN tiffs tf ON tf.active_run_id=r.run_id "
                "JOIN tract_phases tp ON tp.tract_phase_pk=tf.tract_phase_pk "
                "WHERE tp.tract_pk=?",
                (tract_pk,),
            ).fetchall()
            for run in active_runs:
                try:
                    metrics = json.loads(run["metrics_json"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    metrics = {}
                if not isinstance(metrics, dict):
                    metrics = {}
                metrics.pop("canopy_cover_rate", None)
                metrics.pop("canopy_cover_area_m2", None)
                metrics["canopy_cover_status"] = "pending"
                metrics["effective_area_hm2"] = area_hm2
                conn.execute(
                    "UPDATE runs SET metrics_json=? WHERE run_id=?",
                    (json.dumps(metrics, ensure_ascii=False), run["run_id"]),
                )
            conn.commit()
            saved = conn.execute(
                "SELECT tract_pk, boundary_geom, effective_geom, effective_area_hm2, updated_at "
                "FROM tracts WHERE tract_pk=?",
                (tract_pk,),
            ).fetchone()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self._result(saved, boundary, candidate, warnings=warnings, is_default=is_default)

    def inspect_import(
        self,
        tract_pk: str,
        source,
        *,
        layer: str | None = None,
    ) -> EffectiveAreaImportResult:
        from .importers import inspect_vector_source

        imported = inspect_vector_source(source, layer=layer)
        geometry = _parse_geometry(imported.geometry)
        current = self.get(tract_pk)
        boundary = _parse_geometry(current.boundary_geometry)
        requires_clip = not self._within_boundary(geometry, boundary)
        warnings = list(imported.warnings)
        if requires_clip:
            warnings.append("导入几何超出地块边界，保存前需确认裁剪。")
        area = geodesic_area_hm2(geometry)
        return EffectiveAreaImportResult(
            tract_pk=tract_pk,
            geometry=mapping(geometry),
            source_crs=imported.source_crs,
            target_crs="EPSG:4326",
            feature_count=imported.feature_count,
            polygon_count=imported.polygon_count,
            layer=imported.layer,
            layers=imported.layers,
            effective_area_hm2=round(area, 4),
            effective_ratio=(area / current.tract_area_hm2 if current.tract_area_hm2 > 0 else 0.0),
            requires_clip=requires_clip,
            warnings=tuple(warnings),
        )


def _update_tiff_intersections_for_manual_tract(
    conn: sqlite3.Connection,
    tract_pk: str,
    candidate_polygon: Polygon | MultiPolygon,
) -> None:
    """当地块有效区域为 manual 模式时，更新该地块下所有 TIFF 的 area_hm2 为其 footprint 与手绘有效区域的交集公顷数。"""
    from shapely.wkt import loads as load_wkt

    rows = conn.execute(
        "SELECT tf.tiff_id, tf.phase_id, tf.footprint_geom FROM tiffs tf "
        "JOIN tract_phases tp ON tp.tract_phase_pk = tf.tract_phase_pk "
        "WHERE tp.tract_pk=?",
        (tract_pk,),
    ).fetchall()

    for r in rows:
        t_id = r["tiff_id"] if hasattr(r, "keys") else r[0]
        p_id = r["phase_id"] if hasattr(r, "keys") else r[1]
        footprint_wkt = r["footprint_geom"] if hasattr(r, "keys") else r[2]
        if not footprint_wkt:
            continue
        try:
            footprint = load_wkt(footprint_wkt)
            if not footprint.is_valid:
                footprint = footprint.buffer(0)
            inter = footprint.intersection(candidate_polygon)
            inter_area = 0.0 if inter.is_empty else round(geodesic_area_hm2(inter), 4)
            conn.execute(
                "UPDATE tiffs SET effective_area_hm2=? WHERE tiff_id=? AND phase_id=?",
                (inter_area, t_id, p_id),
            )
        except Exception as exc:
            logger.warning("计算 TIFF 交集有效面积失败: tiff_id={} err={}", t_id, exc)
