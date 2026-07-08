"""Administrative naming and raster-coordinate helpers.

The administrative lookup source lives in the API layer (Amap Web Service).
This module keeps only stable local primitives that do not embed a region table.
"""
from __future__ import annotations

from pathlib import Path

UNKNOWN_CITY = "未知市"
UNKNOWN_COUNTY = "未知县"
UNKNOWN_TOWN = "未知"


def normalize_city(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return UNKNOWN_CITY
    if raw.endswith(("市", "自治州", "地区", "盟")):
        return raw
    return raw + "市"


def normalize_county(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return UNKNOWN_COUNTY
    if raw.endswith(("县", "区", "市", "旗", "自治县", "自治旗", "林区", "特区")):
        return raw
    return raw + "县"


def region_id(city: str | None, county: str | None) -> str:
    return f"{normalize_city(city)}_{normalize_county(county)}"


def split_region_id(value: str | None) -> tuple[str, str]:
    if not value or "_" not in value:
        return UNKNOWN_CITY, UNKNOWN_COUNTY
    city, county = value.split("_", 1)
    return normalize_city(city), normalize_county(county)


def inspect_image_center(path: str) -> tuple[float | None, float | None]:
    p = Path(path)
    if p.suffix.lower() not in {".tif", ".tiff", ".img"}:
        return None, None
    try:
        import rasterio
        from rasterio.warp import transform

        with rasterio.open(path) as src:
            x, y = src.transform * (src.width / 2, src.height / 2)
            if src.crs:
                lngs, lats = transform(src.crs, "EPSG:4326", [x], [y])
                return float(lngs[0]), float(lats[0])
            return float(x), float(y)
    except Exception:
        return None, None
