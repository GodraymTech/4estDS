"""Administrative naming and raster-coordinate helpers."""
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


# 这些文件名主干/目录名过于通用（如各航拍目录下统一输出的 map/result_cog.tif），
# 直接用作地块名会导致不同影像共用同一地块，因此需要回退到更具区分度的父目录名。
_GENERIC_TRACT_NAMES = frozenset({"result", "result_cog", "map", "output", "outputs", "ortho", "dom", "mosaic", "cog"})


def default_tract_id(image_path: str | Path) -> str:
    """由影像路径推导默认地块名：文件名主干为通用名时，取最近的非通用父目录名。"""
    path = Path(image_path)
    stem = path.stem
    if stem.lower() not in _GENERIC_TRACT_NAMES:
        return stem
    for parent in path.parents:
        name = parent.name
        if name and name.lower() not in _GENERIC_TRACT_NAMES:
            return name
    return stem


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
                lngs, lats = transform(src.crs, "EPSG:4326", [float(x)], [float(y)])
                return float(lngs[0]), float(lats[0])
            return float(x), float(y)
    except Exception:  # noqa: BLE001
        return None, None
