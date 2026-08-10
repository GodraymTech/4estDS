"""将数据库行转为 GeoJSON FeatureCollection。

复用 export.formats 的 WKT 解析器(DRY)，不重写几何解析逻辑。
前端 MapLibre 直接消费该 FeatureCollection 作为矢量图层。
"""
from __future__ import annotations

from typing import Any, Callable

from ..export.formats import parse_wkt_point, parse_wkt_polygon

# 作为 Feature 属性保留的标销字段(避免把大型几何/内部列泄露到前端)。
_PROPERTY_KEYS = (
    "species", "confidence", "height", "height_source",
    "crown_width_geo", "crown_height_geo",
    "crown_area_geo_real", "crown_area_geo_est",
    "crown_volume_geo_real", "crown_volume_geo_est",
    "run_id", "phase_id", "tiff_id",
)


def _feature(geom: dict | None, props: dict[str, Any]) -> dict | None:
    if geom is None:
        return None
    return {"type": "Feature", "geometry": geom, "properties": props}


def _looks_like_lnglat(x: float, y: float) -> bool:
    return -180 <= x <= 180 and -90 <= y <= 90


def _coordinate_transformer(
    *,
    crs_epsg: int | None = None,
    crs_wkt: str | None = None,
) -> Callable[[list], list]:
    """一次构造坐标转换器，并按整条 ring 批量投影。"""

    def identity(points: list) -> list:
        return [
            [float(point[0]), float(point[1])]
            for point in points
            if isinstance(point, (list, tuple)) and len(point) >= 2
        ]

    if crs_epsg == 4326 or (not crs_epsg and not crs_wkt):
        return identity
    try:
        from rasterio.crs import CRS
        from rasterio.warp import transform

        src_crs = CRS.from_epsg(int(crs_epsg)) if crs_epsg else CRS.from_wkt(crs_wkt)
        if src_crs.to_epsg() == 4326:
            return identity

        def transform_points(points: list) -> list:
            clean = [
                [float(point[0]), float(point[1])]
                for point in points
                if isinstance(point, (list, tuple)) and len(point) >= 2
            ]
            if not clean or _looks_like_lnglat(*clean[0]):
                return clean
            lngs, lats = transform(src_crs, "EPSG:4326", [point[0] for point in clean], [point[1] for point in clean])
            converted = [[float(lng), float(lat)] for lng, lat in zip(lngs, lats)]
            return converted if all(_looks_like_lnglat(*point) for point in converted) else clean

        return transform_points
    except Exception:
        return identity


def _to_wgs84_geometry(
    geom: dict | None,
    *,
    transform_coords: Callable[[list], list],
) -> dict | None:
    if geom is None:
        return None
    if geom.get("type") == "Point":
        coords = transform_coords([geom.get("coordinates")])
        if not coords:
            return None
        return {
            "type": "Point",
            "coordinates": coords[0],
        }
    if geom.get("type") == "Polygon":
        return {
            "type": "Polygon",
            "coordinates": [
                transform_coords(ring)
                for ring in geom.get("coordinates", [])
            ],
        }
    return geom


import json


def _parse_box_geo_polygon(raw: str | list | None) -> dict | None:
    if not raw:
        return None
    try:
        box = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(box, (list, tuple)) and len(box) >= 4:
            min_x, min_y, max_x, max_y = float(box[0]), float(box[1]), float(box[2]), float(box[3])
            return {
                "type": "Polygon",
                "coordinates": [
                    [
                        [min_x, min_y],
                        [max_x, min_y],
                        [max_x, max_y],
                        [min_x, max_y],
                        [min_x, min_y],
                    ]
                ],
            }
    except Exception:
        pass
    return None


def rows_to_featurecollection(
    rows: list[dict],
    *,
    geometry: str = "point",
    crs_epsg: int | None = None,
    crs_wkt: str | None = None,
) -> dict:
    """把观测/规范单木行转为 GeoJSON FeatureCollection。

    Args:
        rows: 每行含 center_geom / crown_geom (WKT) 及属性字段。
        geometry: ``point`` 用 center_geom；``crown`` 用 crown_geom 多边形（若无多边形则降级为 box_geo 矩形面或中心点）。
    """
    features: list[dict] = []
    transform_coords = _coordinate_transformer(crs_epsg=crs_epsg, crs_wkt=crs_wkt)
    for r in rows:
        if geometry == "crown":
            geom = parse_wkt_polygon(r.get("crown_geom")) or _parse_box_geo_polygon(r.get("box_geo")) or parse_wkt_point(r.get("center_geom"))
        else:
            geom = parse_wkt_point(r.get("center_geom")) or parse_wkt_polygon(r.get("crown_geom"))
        geom = _to_wgs84_geometry(geom, transform_coords=transform_coords)
        props = {k: r.get(k) for k in _PROPERTY_KEYS if r.get(k) is not None}
        # 保留一个稳定 id 便于前端选中/高亮。
        props["id"] = r.get("observation_id") or r.get("individual_id")
        feat = _feature(geom, props)
        if feat is not None:
            features.append(feat)
    return {"type": "FeatureCollection", "features": features}
