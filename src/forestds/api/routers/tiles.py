"""本地 GeoTIFF XYZ 瓦片服务。

这是面向单机/内网开发的轻量瓦片端点：从 runs 关联的本地 TIFF 按
WebMercator XYZ 实时切 256px PNG。它不替代生产级 TiTiler，但能让已有 COG /
带外部概览的 tiled TIFF 直接在前端加载。
"""
from __future__ import annotations

import hashlib
import os
from io import BytesIO
from math import pi
from pathlib import Path
from threading import Semaphore

from fastapi import APIRouter, Depends, HTTPException, Response

from ..deps import get_db_url

try:  # geo 依赖不是 API 核心最小依赖，缺失时只禁用瓦片端点。
    import numpy as np
    import rasterio
    from PIL import Image
    from rasterio.enums import Resampling
    from rasterio.errors import RasterioIOError
    from rasterio.transform import from_bounds as transform_from_bounds
    from rasterio.warp import reproject, transform_bounds
except ImportError:  # pragma: no cover - 取决于部署 extras
    np = None
    rasterio = None
    Image = None
    Resampling = None
    RasterioIOError = Exception
    reproject = None
    transform_bounds = None
    transform_from_bounds = None


router = APIRouter(prefix="/tiles", tags=["tiles"])

WEB_MERCATOR_EXTENT = pi * 6378137.0
TILE_SIZE = 256
MAX_TILE_ZOOM = 24


def _tile_int_setting(key: str, env_name: str, default: int, *, minimum: int) -> int:
    raw = os.environ.get(env_name)
    if raw is None:
        try:
            from ...config import load_settings

            raw = load_settings().get(f"tiles.{key}", default)
        except Exception:
            raw = default
    try:
        return max(minimum, int(raw))
    except (TypeError, ValueError):
        return max(minimum, default)


def _tile_bool_setting(key: str, env_name: str, default: bool) -> bool:
    raw = os.environ.get(env_name)
    if raw is None:
        try:
            from ...config import load_settings

            raw = load_settings().get(f"tiles.{key}", default)
        except Exception:
            raw = default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


TILE_RENDER_CONCURRENCY = _tile_int_setting("render_concurrency", "FORESTDS_TILE_RENDER_CONCURRENCY", 2, minimum=1)
TILE_GDAL_CACHE_MB = _tile_int_setting("gdal_cache_mb", "FORESTDS_TILE_GDAL_CACHE_MB", 64, minimum=8)
TILE_WARP_MEM_MB = _tile_int_setting("warp_mem_mb", "FORESTDS_TILE_WARP_MEM_MB", 32, minimum=8)
TILE_CACHE_ENABLED = _tile_bool_setting("cache_enabled", "FORESTDS_TILE_CACHE_ENABLED", True)
_TILE_RENDER_SEMAPHORE = Semaphore(TILE_RENDER_CONCURRENCY)


@router.get("/tracts/{tract_id}/{z}/{x}/{y}", summary="地块本地 TIFF XYZ PNG 瓦片")
def get_tract_tile(
    tract_id: str,
    z: int,
    x: int,
    y: int,
    db_url: str | None = Depends(get_db_url),
) -> Response:
    _validate_xyz(z, x, y)
    path = _resolve_tract_image_path(tract_id, db_url)
    content, cache_status = _render_tile_cached(path, z, x, y)
    return Response(
        content=content,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400", "X-ForestDS-Tile-Cache": cache_status},
    )


@router.get("/tiffs/{phase_id}/{tiff_ref}/{z}/{x}/{y}", summary="单 TIFF 本地 XYZ PNG 瓦片")
def get_tiff_tile(
    phase_id: str,
    tiff_ref: str,
    z: int,
    x: int,
    y: int,
    db_url: str | None = Depends(get_db_url),
) -> Response:
    _validate_xyz(z, x, y)
    path = _resolve_tiff_image_path(phase_id, tiff_ref, db_url)
    content, cache_status = _render_tile_cached(path, z, x, y)
    return Response(
        content=content,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400", "X-ForestDS-Tile-Cache": cache_status},
    )


def _validate_xyz(z: int, x: int, y: int) -> None:
    if z < 0 or z > MAX_TILE_ZOOM:
        raise HTTPException(status_code=400, detail=f"瓦片层级超出范围: {z}")
    limit = 2**z
    if x < 0 or y < 0 or x >= limit or y >= limit:
        raise HTTPException(status_code=400, detail="瓦片 x/y 超出当前层级范围")


def _resolve_tract_image_path(tract_id: str, db_url: str | None) -> Path:
    from ...db import reader

    raw_path = reader.latest_tiff_path_for_tract(tract_id, url=db_url)
    if not raw_path:
        run_id = reader.active_run_for_tract(tract_id, url=db_url) or reader.latest_run_for_tract(
            tract_id, url=db_url
        )
        run = reader.get_run(run_id, url=db_url) if run_id else None
        raw_path = run.get("input_path") if run else None
    if not raw_path:
        raise HTTPException(status_code=404, detail="该地块没有关联可切片的原始影像")

    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"影像文件不存在: {path}")
    if path.suffix.lower() not in {".tif", ".tiff"}:
        raise HTTPException(status_code=415, detail="当前瓦片服务只支持 GeoTIFF")
    return path


def _resolve_tiff_image_path(phase_id: str, tiff_ref: str, db_url: str | None) -> Path:
    from ...db import reader

    raw_path = reader.tiff_path(phase_id=phase_id, file_name=tiff_ref, url=db_url)
    if not raw_path:
        raise HTTPException(status_code=404, detail="该 TIFF 没有关联可切片的原始影像")
    return _validate_image_path(raw_path)


def _validate_image_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"影像文件不存在: {path}")
    if path.suffix.lower() not in {".tif", ".tiff"}:
        raise HTTPException(status_code=415, detail="当前瓦片服务只支持 GeoTIFF")
    return path


def _render_tile_cached(path: Path, z: int, x: int, y: int) -> tuple[bytes, str]:
    if not TILE_CACHE_ENABLED:
        return _render_tile(path, z, x, y), "BYPASS"

    cache_path = _tile_cache_path(path, z, x, y)
    if cache_path.is_file():
        return cache_path.read_bytes(), "HIT"

    content = _render_tile(path, z, x, y)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = cache_path.with_name(f".{cache_path.name}.{os.getpid()}.tmp")
        tmp_path.write_bytes(content)
        os.replace(tmp_path, cache_path)
    except OSError:
        pass
    return content, "MISS"


def _tile_cache_path(path: Path, z: int, x: int, y: int) -> Path:
    from ... import paths

    stat = path.stat()
    raw = "|".join(
        [
            "v1",
            str(path),
            str(stat.st_size),
            str(stat.st_mtime_ns),
            str(TILE_SIZE),
            str(z),
            str(x),
            str(y),
        ]
    )
    digest = hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()
    return paths.subdir("cache") / "tiles" / digest[:2] / digest[2:4] / f"{digest}.png"


def _render_tile(path: Path, z: int, x: int, y: int) -> bytes:
    if rasterio is None or np is None or Image is None or reproject is None:
        raise HTTPException(status_code=503, detail="缺少 rasterio/numpy/Pillow，无法切片")
    from ...preprocess.cog import TIFF_FORMAT_LABELS, inspect_tiff_format, is_tiff_tile_ready

    fmt = inspect_tiff_format(path)
    if not is_tiff_tile_ready(fmt):
        raise HTTPException(
            status_code=422,
            detail=f"影像不是可高效瓦片读取的 TIFF，拒绝实时重投影以避免高内存占用: {TIFF_FORMAT_LABELS.get(fmt, fmt)}",
        )

    bounds = _tile_bounds_3857(z, x, y)
    try:
        with _TILE_RENDER_SEMAPHORE:
            with rasterio.Env(
                GDAL_CACHEMAX=TILE_GDAL_CACHE_MB,
                GDAL_NUM_THREADS="1",
                NUM_THREADS="1",
            ):
                with rasterio.open(path, sharing=False) as src:
                    if not src.crs:
                        raise HTTPException(status_code=422, detail="影像缺少 CRS，无法投影到瓦片坐标系")
                    if not _intersects(bounds, transform_bounds(src.crs, "EPSG:3857", *src.bounds)):
                        return _transparent_png()

                    dst_transform = transform_from_bounds(*bounds, TILE_SIZE, TILE_SIZE)
                    data = np.full(
                        (len(_display_indexes(src.count)), TILE_SIZE, TILE_SIZE),
                        np.nan,
                        dtype="float32",
                    )
                    for out_idx, band_idx in enumerate(_display_indexes(src.count)):
                        reproject(
                            source=rasterio.band(src, band_idx),
                            destination=data[out_idx],
                            src_transform=src.transform,
                            src_crs=src.crs,
                            src_nodata=src.nodata,
                            dst_transform=dst_transform,
                            dst_crs="EPSG:3857",
                            dst_nodata=np.nan,
                            resampling=Resampling.bilinear,
                            warp_mem_limit=TILE_WARP_MEM_MB,
                        )
    except HTTPException:
        raise
    except RasterioIOError as exc:
        raise HTTPException(status_code=404, detail=f"影像无法读取: {path}") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"瓦片渲染失败: {exc}") from exc

    return _to_png(data)


def _tile_bounds_3857(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    resolution = (WEB_MERCATOR_EXTENT * 2) / (TILE_SIZE * (2**z))
    minx = -WEB_MERCATOR_EXTENT + x * TILE_SIZE * resolution
    maxx = -WEB_MERCATOR_EXTENT + (x + 1) * TILE_SIZE * resolution
    maxy = WEB_MERCATOR_EXTENT - y * TILE_SIZE * resolution
    miny = WEB_MERCATOR_EXTENT - (y + 1) * TILE_SIZE * resolution
    return minx, miny, maxx, maxy


def _intersects(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])


def _display_indexes(count: int) -> list[int]:
    if count >= 3:
        return [1, 2, 3]
    return [1]


def _to_png(data) -> bytes:
    values = np.asarray(np.ma.filled(data, np.nan), dtype="float32")
    mask = np.ma.getmaskarray(data) | ~np.isfinite(values)
    values = np.nan_to_num(values, nan=0.0)
    if values.ndim == 2:
        values = values[np.newaxis, :, :]
        mask = mask[np.newaxis, :, :]

    bands = [_scale_to_uint8(values[i], mask[i]) for i in range(values.shape[0])]
    if len(bands) == 1:
        rgb = np.stack([bands[0], bands[0], bands[0]], axis=-1)
    else:
        rgb = np.stack(bands[:3], axis=-1)

    alpha = np.where(np.all(mask, axis=0), 0, 255).astype("uint8")
    rgba = np.dstack([rgb, alpha])
    img = Image.fromarray(rgba)
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _scale_to_uint8(band, mask) -> "np.ndarray":
    arr = np.asarray(band)
    if arr.dtype == np.uint8:
        return arr

    valid = arr[~mask]
    valid = valid[np.isfinite(valid)]
    if valid.size == 0:
        return np.zeros(arr.shape, dtype="uint8")
    vmin = float(valid.min())
    vmax = float(valid.max())
    if 0 <= vmin and vmax <= 255:
        return np.clip(arr, 0, 255).astype("uint8")

    lo, hi = np.percentile(valid, [2, 98])
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        lo, hi = vmin, vmax
    if hi <= lo:
        return np.zeros(arr.shape, dtype="uint8")
    scaled = (arr.astype("float32") - float(lo)) * (255.0 / float(hi - lo))
    return np.clip(scaled, 0, 255).astype("uint8")


def _transparent_png() -> bytes:
    img = Image.fromarray(np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype="uint8"))
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
