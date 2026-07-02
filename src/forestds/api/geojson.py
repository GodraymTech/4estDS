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
)


def _feature(geom: dict | None, props: dict[str, Any]) -> dict | None:
    if geom is None:
        return None
    return {"type": "Feature", "geometry": geom, "properties": props}


def rows_to_featurecollection(rows: list[dict], *, geometry: str = "point") -> dict:
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
            geom = parse_wkt_point(r.get("geom_point"))
        props = {k: r.get(k) for k in _PROPERTY_KEYS if r.get(k) is not None}
        # 保留一个稳定 id 便于前端选中/高亮。
        props["id"] = r.get("obs_id") or r.get("canonical_id")
        feat = _feature(geom, props)
        if feat is not None:
            features.append(feat)
    return {"type": "FeatureCollection", "features": features}
