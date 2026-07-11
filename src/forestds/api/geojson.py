"""将数据库行转为 GeoJSON FeatureCollection。

复用 export.formats 的 WKT 解析器(DRY)，不重写几何解析逻辑。
前端 MapLibre 直接消费该 FeatureCollection 作为矢量图层。
"""
from __future__ import annotations

from typing import Any

from ..export.formats import parse_wkt_point, parse_wkt_polygon

# 作为 Feature 属性保留的标销字段(避免把大型几何/内部列泄露到前端)。
_PROPERTY_KEYS = (
    "species", "confidence", "height", "height_source",
    "crown_area_geo_real", "crown_area_geo_est",
    "crown_volume_geo_real", "crown_volume_geo_est",
    "phase_id", "tiff_id",
)


def _feature(geom: dict | None, props: dict[str, Any]) -> dict | None:
    if geom is None:
        return None
    return {"type": "Feature", "geometry": geom, "properties": props}


def _looks_like_lnglat(x: float, y: float) -> bool:
    return -180 <= x <= 180 and -90 <= y <= 90


def _transform_coords(coords, *, crs_epsg: int | None = None, crs_wkt: str | None = None):
    if not coords or len(coords) < 2:
        return coords
    x, y = float(coords[0]), float(coords[1])
    if crs_epsg == 4326 or _looks_like_lnglat(x, y):
        return [x, y]
    if not crs_epsg and not crs_wkt:
        return [x, y]
    try:
        from rasterio.crs import CRS
        from rasterio.warp import transform

        src_crs = CRS.from_epsg(int(crs_epsg)) if crs_epsg else CRS.from_wkt(crs_wkt)
        lngs, lats = transform(src_crs, "EPSG:4326", [x], [y])
        lng, lat = float(lngs[0]), float(lats[0])
        return [lng, lat] if _looks_like_lnglat(lng, lat) else [x, y]
    except Exception:
        return [x, y]


def _to_wgs84_geometry(
    geom: dict | None,
    *,
    crs_epsg: int | None = None,
    crs_wkt: str | None = None,
) -> dict | None:
    if geom is None:
        return None
    if geom.get("type") == "Point":
        return {
            "type": "Point",
            "coordinates": _transform_coords(
                geom.get("coordinates"), crs_epsg=crs_epsg, crs_wkt=crs_wkt
            ),
        }
    if geom.get("type") == "Polygon":
        return {
            "type": "Polygon",
            "coordinates": [
                [
                    _transform_coords(pt, crs_epsg=crs_epsg, crs_wkt=crs_wkt)
                    for pt in ring
                ]
                for ring in geom.get("coordinates", [])
            ],
        }
    return geom


def rows_to_featurecollection(
    rows: list[dict],
    *,
    geometry: str = "point",
    crs_epsg: int | None = None,
    crs_wkt: str | None = None,
) -> dict:
    """把观测/规范单木行转为 GeoJSON FeatureCollection。

    Args:
        rows: 每行含 geom_point / geom_crown (WKT) 及属性字段。
        geometry: ``point`` 用 geom_point；``crown`` 用 geom_crown 多边形。
    """
    features: list[dict] = []
    for r in rows:
        if geometry == "crown":
            geom = parse_wkt_polygon(r.get("geom_crown"))
        else:
            geom = parse_wkt_point(r.get("center_geom")) or parse_wkt_point(r.get("geom_point"))
        geom = _to_wgs84_geometry(geom, crs_epsg=crs_epsg, crs_wkt=crs_wkt)
        props = {k: r.get(k) for k in _PROPERTY_KEYS if r.get(k) is not None}
        # 保留一个稳定 id 便于前端选中/高亮。
        props["id"] = r.get("observation_id") or r.get("individual_id")
        feat = _feature(geom, props)
        if feat is not None:
            features.append(feat)
    return {"type": "FeatureCollection", "features": features}
