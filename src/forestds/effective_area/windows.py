"""有效区域的像素窗调度、局部掩膜与有界 LRU 缓存。"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Sequence
import sqlite3
from threading import RLock
from typing import Literal, TypeAlias

import numpy as np
from affine import Affine
from pyproj import CRS, Transformer
from shapely import transform as transform_geometry
from shapely.geometry import Point, box, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.prepared import prep
from shapely.wkt import loads as load_wkt

from ..db.schema import resolve_db_path


WindowClass: TypeAlias = Literal["inside", "outside", "boundary"]
CacheKey: TypeAlias = tuple[str, str, str, tuple[float, ...]]


def _affine(value: Affine | Sequence[float]) -> Affine:
    if isinstance(value, Affine):
        return value
    values = tuple(float(item) for item in value)
    if len(values) < 6:
        raise ValueError("geotransform 至少需要 6 个数值")
    return Affine(*values[:6])


def effective_window_cache_key(
    tract_pk: str,
    tract_updated_at: str,
    tiff_id: str,
    geotransform: Affine | Sequence[float],
) -> CacheKey:
    transform = _affine(geotransform)
    return (str(tract_pk), str(tract_updated_at), str(tiff_id), tuple(float(v) for v in transform))


def _window_values(window) -> tuple[int, int, int, int]:
    if isinstance(window, Sequence) and not isinstance(window, (str, bytes)):
        if len(window) != 4:
            raise ValueError("window 必须是 (x, y, w, h)")
        x, y, w, h = window
    else:
        x, y, w, h = window.x, window.y, window.w, window.h
    return int(x), int(y), int(w), int(h)


class EffectiveWindowFilter:
    """在 TIFF 像素坐标中执行两级 window 判断与中心点过滤。"""

    def __init__(self, pixel_geometry: BaseGeometry, *, cache_key: CacheKey | None = None):
        if pixel_geometry.is_empty:
            raise ValueError("pixel_geometry 不能为空")
        self.pixel_geometry = pixel_geometry
        self.cache_key = cache_key
        self.effective_area_hm2: float | None = None
        self._prepared = prep(pixel_geometry)
        self._bbox = pixel_geometry.bounds

    @classmethod
    def from_pixel_geometry(cls, geometry: BaseGeometry) -> "EffectiveWindowFilter":
        return cls(geometry)

    @classmethod
    def from_world_geometry(
        cls,
        geometry: dict,
        *,
        raster_crs: str | CRS,
        geotransform: Affine | Sequence[float],
        tract_pk: str,
        tract_updated_at: str,
        tiff_id: str,
    ) -> "EffectiveWindowFilter":
        transform = _affine(geotransform)
        world_geometry = shape(geometry)
        target_crs = CRS.from_user_input(raster_crs)
        if target_crs.to_epsg() != 4326:
            projector = Transformer.from_crs(4326, target_crs, always_xy=True)
            world_geometry = transform_geometry(
                world_geometry,
                projector.transform,
                interleaved=False,
            )
        inverse = ~transform

        def to_pixel(x, y):
            return (
                inverse.a * np.asarray(x) + inverse.b * np.asarray(y) + inverse.c,
                inverse.d * np.asarray(x) + inverse.e * np.asarray(y) + inverse.f,
            )

        pixel_geometry = transform_geometry(world_geometry, to_pixel, interleaved=False)
        key = effective_window_cache_key(tract_pk, tract_updated_at, tiff_id, transform)
        return cls(pixel_geometry, cache_key=key)

    def classify(self, window) -> WindowClass:
        x, y, width, height = _window_values(window)
        if width <= 0 or height <= 0:
            return "outside"
        minx, miny, maxx, maxy = self._bbox
        if x + width <= minx or x >= maxx or y + height <= miny or y >= maxy:
            return "outside"
        window_geometry = box(x, y, x + width, y + height)
        if self._prepared.covers(window_geometry):
            return "inside"
        intersection = self.pixel_geometry.intersection(window_geometry)
        if intersection.is_empty or intersection.area <= 0:
            return "outside"
        return "boundary"

    def local_mask(self, window) -> np.ndarray | None:
        if self.classify(window) != "boundary":
            return None
        x, y, width, height = _window_values(window)
        from rasterio.features import rasterize

        values = rasterize(
            [(self.pixel_geometry, 1)],
            out_shape=(height, width),
            transform=Affine.translation(x, y),
            fill=0,
            default_value=1,
            all_touched=False,
            dtype="uint8",
        )
        return values.astype(np.bool_, copy=False)

    def keep_detection(self, center_px: tuple[float, float]) -> bool:
        return bool(self._prepared.covers(Point(float(center_px[0]), float(center_px[1]))))


class EffectiveWindowCache:
    """按地块/版本/TIFF/仿射变换缓存像素几何，不缓存全图 mask。"""

    def __init__(self, max_size: int = 32):
        self.max_size = max(1, int(max_size))
        self._values: OrderedDict[CacheKey, EffectiveWindowFilter] = OrderedDict()
        self._lock = RLock()

    def get_or_create(
        self,
        key: CacheKey,
        factory: Callable[[], EffectiveWindowFilter],
    ) -> EffectiveWindowFilter:
        with self._lock:
            existing = self._values.pop(key, None)
            if existing is not None:
                self._values[key] = existing
                return existing
            created = factory()
            self._values[key] = created
            while len(self._values) > self.max_size:
                self._values.popitem(last=False)
            return created

    def clear(self) -> None:
        with self._lock:
            self._values.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._values)


_CACHE_REGISTRY: dict[int, EffectiveWindowCache] = {}
_CACHE_REGISTRY_LOCK = RLock()


def _cache_for_size(max_size: int) -> EffectiveWindowCache:
    bounded = max(1, int(max_size))
    with _CACHE_REGISTRY_LOCK:
        cache = _CACHE_REGISTRY.get(bounded)
        if cache is None:
            cache = EffectiveWindowCache(bounded)
            _CACHE_REGISTRY[bounded] = cache
        return cache


def load_effective_window_filter(
    *,
    db_url: str | None,
    tract_ref: str,
    phase_id: str | None,
    tiff_id: str | None,
    raster_crs: str | CRS | None,
    geotransform: Affine | Sequence[float] | None,
    image_path: str | None = None,
    cache_size: int = 32,
) -> EffectiveWindowFilter | None:
    """从当前地块版本构建/复用像素几何；新地块或无地理参考时不启用过滤。"""
    if not tract_ref or raster_crs is None or geotransform is None:
        return None
    conn = sqlite3.connect(resolve_db_path(db_url))
    conn.row_factory = sqlite3.Row
    try:
        clauses = ["(tr.tract_pk=? OR tr.tract_id=?)"]
        params: list[object] = [tract_ref, tract_ref]
        if phase_id:
            clauses.append("tp.phase_id=?")
            params.append(phase_id)
        if tiff_id:
            clauses.append("tf.tiff_id=?")
            params.append(tiff_id)
        elif image_path:
            clauses.append("(tf.path_versions LIKE ? OR tf.file_name IN (?, ?))")
            from pathlib import Path

            image = Path(image_path)
            params.extend([f"%{image_path}%", image.name, image.stem])
        row = conn.execute(
            "SELECT tr.tract_pk, tr.updated_at, tr.boundary_geom, tr.effective_geom, "
            "tr.effective_area_hm2, tf.tiff_id "
            "FROM tracts tr "
            "JOIN tract_phases tp ON tp.tract_pk=tr.tract_pk "
            "JOIN tiffs tf ON tf.tract_phase_pk=tp.tract_phase_pk "
            "WHERE " + " AND ".join(clauses) + " "
            "ORDER BY tp.phase_id DESC, tf.updated_at DESC LIMIT 1",
            params,
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    raw_geometry = row["effective_geom"] or row["boundary_geom"]
    if not raw_geometry:
        return None
    transform = _affine(geotransform)
    key = effective_window_cache_key(
        row["tract_pk"],
        row["updated_at"],
        row["tiff_id"],
        transform,
    )

    def create() -> EffectiveWindowFilter:
        value = EffectiveWindowFilter.from_world_geometry(
            mapping(load_wkt(raw_geometry)),
            raster_crs=raster_crs,
            geotransform=transform,
            tract_pk=row["tract_pk"],
            tract_updated_at=row["updated_at"],
            tiff_id=row["tiff_id"],
        )
        value.effective_area_hm2 = row["effective_area_hm2"]
        return value

    return _cache_for_size(cache_size).get_or_create(key, create)
