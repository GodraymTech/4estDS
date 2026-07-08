"""Geographic search and reverse-geocoding proxy endpoints."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from fastapi import APIRouter, HTTPException, Query

from ...geo_admin import UNKNOWN_COUNTY, UNKNOWN_TOWN, normalize_city, normalize_county, region_id
from ...geo_coords import gcj02_to_wgs84, wgs84_to_gcj02
from ..schemas import GeoPlaceOut, GeoReverseOut, GeoSearchOut

router = APIRouter(prefix="/geo", tags=["geo"])

_AMAP_BASE = "https://restapi.amap.com/v3"
_CACHE_TTL_S = 300
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


class AmapConfigError(RuntimeError):
    pass


class AmapServiceError(RuntimeError):
    def __init__(self, message: str, *, info: str | None = None, infocode: str | None = None) -> None:
        super().__init__(message)
        self.info = info
        self.infocode = infocode


@dataclass(frozen=True)
class ReverseAdmin:
    city: str
    county: str
    town: str
    region_id: str
    formatted_address: str | None = None
    adcode: str | None = None


def _key() -> str:
    key = os.environ.get("AMAP_WEB_SERVICE_KEY") or os.environ.get("FORESTDS_AMAP_KEY")
    if not key:
        raise AmapConfigError("未配置 AMAP_WEB_SERVICE_KEY")
    return key


def _first_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list):
        for item in value:
            text = _first_text(item)
            if text:
                return text
    return None


def _request(path: str, params: dict[str, Any]) -> dict[str, Any]:
    params = {k: v for k, v in params.items() if v not in (None, "")}
    params["key"] = _key()
    url = f"{_AMAP_BASE}/{path}?{urlencode(params)}"
    cached = _CACHE.get(url)
    now = time.time()
    if cached and now - cached[0] < _CACHE_TTL_S:
        return cached[1]
    try:
        with urlopen(url, timeout=4) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise AmapServiceError(f"高德服务请求失败: {exc}") from exc
    if str(body.get("status")) != "1":
        info = str(body.get("info") or "未知错误")
        infocode = str(body.get("infocode") or "")
        raise AmapServiceError(f"高德服务返回失败: {info}", info=info, infocode=infocode)
    _CACHE[url] = (now, body)
    if len(_CACHE) > 256:
        for old_key in list(_CACHE)[:64]:
            _CACHE.pop(old_key, None)
    return body


def _parse_location(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, str) or "," not in value:
        return None
    lng_raw, lat_raw = value.split(",", 1)
    try:
        return float(lng_raw), float(lat_raw)
    except ValueError:
        return None


def _place_from_geocode(item: dict[str, Any]) -> GeoPlaceOut | None:
    loc = _parse_location(item.get("location"))
    if not loc:
        return None
    lng, lat = gcj02_to_wgs84(*loc)
    city = _first_text(item.get("city")) or _first_text(item.get("province"))
    county = _first_text(item.get("district"))
    town = _first_text(item.get("township"))
    name = _first_text(item.get("formatted_address")) or _first_text(item.get("district")) or _first_text(item.get("city"))
    if not name:
        return None
    return GeoPlaceOut(
        id="geocode:" + str(item.get("adcode") or name),
        name=name,
        address=_first_text(item.get("formatted_address")),
        city=normalize_city(city) if city else None,
        county=normalize_county(county) if county else None,
        town=town,
        adcode=_first_text(item.get("adcode")),
        lng=lng,
        lat=lat,
        source="amap-geocode",
    )


def _place_from_poi(item: dict[str, Any]) -> GeoPlaceOut | None:
    loc = _parse_location(item.get("location"))
    if not loc:
        return None
    lng, lat = gcj02_to_wgs84(*loc)
    name = _first_text(item.get("name"))
    if not name:
        return None
    city = _first_text(item.get("cityname"))
    county = _first_text(item.get("adname"))
    return GeoPlaceOut(
        id="poi:" + str(item.get("id") or f"{name}:{loc[0]:.6f},{loc[1]:.6f}"),
        name=name,
        address=_first_text(item.get("address")),
        city=normalize_city(city) if city else None,
        county=normalize_county(county) if county else None,
        adcode=_first_text(item.get("adcode")),
        lng=lng,
        lat=lat,
        source="amap-poi",
    )


def search_places(query: str, *, city: str = "广东", limit: int = 10) -> list[GeoPlaceOut]:
    q = query.strip()
    if not q:
        return []
    limit = max(1, min(limit, 25))
    results: list[GeoPlaceOut] = []
    seen: set[str] = set()

    geo_body = _search_request("geocode/geo", {"address": q, "city": city, "output": "json"})
    for item in geo_body.get("geocodes") or []:
        if not isinstance(item, dict):
            continue
        place = _place_from_geocode(item)
        if place and place.id not in seen:
            seen.add(place.id)
            results.append(place)

    if len(results) < limit:
        poi_body = _search_request(
            "place/text",
            {
                "keywords": q,
                "city": city,
                "citylimit": "false",
                "offset": min(limit, 25),
                "page": 1,
                "extensions": "base",
                "output": "json",
            },
        )
        for item in poi_body.get("pois") or []:
            if not isinstance(item, dict):
                continue
            place = _place_from_poi(item)
            if place and place.id not in seen:
                seen.add(place.id)
                results.append(place)
                if len(results) >= limit:
                    break
    return results[:limit]


def _search_request(path: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        return _request(path, params)
    except AmapServiceError as exc:
        if exc.info == "ENGINE_RESPONSE_DATA_ERROR":
            return {}
        raise


def reverse_admin(lng: float | None, lat: float | None) -> ReverseAdmin:
    if lng is None or lat is None:
        return ReverseAdmin("未知市", UNKNOWN_COUNTY, UNKNOWN_TOWN, region_id(None, None))
    gcj_lng, gcj_lat = wgs84_to_gcj02(lng, lat)
    body = _request(
        "geocode/regeo",
        {
            "location": f"{gcj_lng:.8f},{gcj_lat:.8f}",
            "radius": 1000,
            "extensions": "base",
            "output": "json",
        },
    )
    regeo = body.get("regeocode") or {}
    component = regeo.get("addressComponent") or {}
    province = _first_text(component.get("province"))
    city = _first_text(component.get("city")) or province
    county = _first_text(component.get("district"))
    town = _first_text(component.get("township")) or UNKNOWN_TOWN
    normalized_city = normalize_city(city)
    normalized_county = normalize_county(county)
    return ReverseAdmin(
        city=normalized_city,
        county=normalized_county,
        town=town,
        region_id=region_id(normalized_city, normalized_county),
        formatted_address=_first_text(regeo.get("formatted_address")),
        adcode=_first_text(component.get("adcode")),
    )


@router.get("/search", response_model=GeoSearchOut, summary="高德地名搜索")
def search_endpoint(
    q: str = Query(..., min_length=1),
    city: str = Query("广东"),
    limit: int = Query(10, ge=1, le=25),
) -> GeoSearchOut:
    try:
        return GeoSearchOut(query=q, places=search_places(q, city=city, limit=limit))
    except AmapConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AmapServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/reverse", response_model=GeoReverseOut, summary="高德逆地理编码")
def reverse_endpoint(lng: float = Query(...), lat: float = Query(...)) -> GeoReverseOut:
    try:
        item = reverse_admin(lng, lat)
    except AmapConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AmapServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return GeoReverseOut(**item.__dict__, lng=lng, lat=lat)
