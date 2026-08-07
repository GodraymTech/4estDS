"""实例 mask 的紧凑存储、画笔编辑、像素/地理几何转换。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import numpy as np
from affine import Affine
from rasterio.features import shapes
from shapely import transform as transform_geometry
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid

from .domain import ReviewValidationError


@dataclass(frozen=True)
class MaskGeometry:
    pixel_geometry: BaseGeometry
    geometry: BaseGeometry
    pixel_bounds: tuple[float, float, float, float]


def _source_window(value: Iterable[float]) -> tuple[float, float, float, float]:
    try:
        x, y, width, height = [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise ReviewValidationError("mask 来源窗口格式无效。", code="invalid_source_window") from exc
    if width <= 0 or height <= 0:
        raise ReviewValidationError("mask 来源窗口宽高必须大于零。", code="invalid_source_window")
    return x, y, width, height


def encode_mask(mask: Any) -> dict[str, Any]:
    values = np.asarray(mask, dtype=bool)
    if values.ndim != 2:
        raise ReviewValidationError("实例 mask 必须是二维数组。", code="invalid_mask")
    flat = values.ravel(order="C")
    counts: list[int] = []
    current = False
    count = 0
    for value in flat:
        flag = bool(value)
        if flag == current:
            count += 1
        else:
            counts.append(count)
            current = flag
            count = 1
    counts.append(count)
    return {"height": values.shape[0], "width": values.shape[1], "counts": counts}


def decode_mask(value: Mapping[str, Any]) -> np.ndarray:
    try:
        height, width = int(value["height"]), int(value["width"])
        counts = [int(item) for item in value["counts"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise ReviewValidationError("mask RLE 格式无效。", code="invalid_mask_rle") from exc
    if height <= 0 or width <= 0 or any(count < 0 for count in counts) or sum(counts) != height * width:
        raise ReviewValidationError("mask RLE 尺寸不一致。", code="invalid_mask_rle")
    flat = np.zeros(height * width, dtype=bool)
    offset = 0
    value_flag = False
    for count in counts:
        if value_flag:
            flat[offset:offset + count] = True
        offset += count
        value_flag = not value_flag
    return flat.reshape((height, width))


def normalize_crown_geometry(geometry: BaseGeometry, tolerance: float = 0.0) -> MultiPolygon:
    candidate = make_valid(geometry)
    if tolerance > 0:
        candidate = make_valid(candidate.simplify(float(tolerance), preserve_topology=True))
    polygons: list[Polygon] = []
    if isinstance(candidate, Polygon):
        polygons = [candidate]
    elif isinstance(candidate, MultiPolygon):
        polygons = list(candidate.geoms)
    elif isinstance(candidate, GeometryCollection):
        for item in candidate.geoms:
            if isinstance(item, Polygon):
                polygons.append(item)
            elif isinstance(item, MultiPolygon):
                polygons.extend(item.geoms)
    polygons = [polygon for polygon in polygons if not polygon.is_empty and polygon.area > 0]
    if not polygons:
        raise ReviewValidationError("mask 轮廓为空。", code="empty_mask")
    result = MultiPolygon(polygons).normalize()
    if not result.is_valid:
        raise ReviewValidationError("mask 轮廓无法规范化为有效面。", code="invalid_mask_geometry")
    return result


def mask_to_tiff_geometry(
    mask: Any,
    source_window: Iterable[float],
    transform: Affine,
    *,
    tolerance_px: float = 0.75,
) -> MaskGeometry:
    values = np.asarray(mask, dtype=bool)
    if values.ndim != 2 or not values.any():
        raise ReviewValidationError("实例 mask 不能为空。", code="empty_mask")
    x, y, width, height = _source_window(source_window)
    mask_transform = Affine(width / values.shape[1], 0, x, 0, height / values.shape[0], y)
    parts = [
        shape(geometry)
        for geometry, value in shapes(values.astype("uint8"), mask=values, transform=mask_transform)
        if int(value) == 1
    ]
    pixel = normalize_crown_geometry(unary_union(parts), tolerance=tolerance_px)

    def project(x_coordinates: Any, y_coordinates: Any) -> tuple[Any, Any]:
        return (
            transform.a * x_coordinates + transform.b * y_coordinates + transform.c,
            transform.d * x_coordinates + transform.e * y_coordinates + transform.f,
        )

    geographic = transform_geometry(pixel, project, interleaved=False)
    geographic = normalize_crown_geometry(geographic, tolerance=0)
    return MaskGeometry(pixel_geometry=pixel, geometry=geographic, pixel_bounds=tuple(float(value) for value in pixel.bounds))


def apply_brush(
    encoded_mask: Mapping[str, Any],
    source_window: Iterable[float],
    strokes: Iterable[Mapping[str, Any]],
) -> np.ndarray:
    mask = decode_mask(encoded_mask)
    x, y, width, height = _source_window(source_window)
    yy, xx = np.ogrid[:mask.shape[0], :mask.shape[1]]
    for stroke in strokes:
        mode = str(stroke.get("mode") or "add")
        if mode not in {"add", "erase"}:
            raise ReviewValidationError("画笔模式必须是 add 或 erase。", code="invalid_mask_brush")
        try:
            cx = (float(stroke["x"]) - x) * mask.shape[1] / width
            cy = (float(stroke["y"]) - y) * mask.shape[0] / height
            radius_px = float(stroke.get("radius") or 1)
        except (KeyError, TypeError, ValueError) as exc:
            raise ReviewValidationError("mask 画笔坐标无效。", code="invalid_mask_brush") from exc
        if radius_px <= 0:
            raise ReviewValidationError("mask 画笔半径必须大于零。", code="invalid_mask_brush")
        radius = max(0.5, radius_px * max(mask.shape) / max(width, height))
        disk = (xx - cx) ** 2 + (yy - cy) ** 2 <= radius ** 2
        mask[disk] = mode == "add"
    return mask


def mask_item_fields(mask: Any, source_window: Iterable[float], transform: Affine) -> dict[str, Any]:
    window = _source_window(source_window)
    result = mask_to_tiff_geometry(mask, window, transform)
    return {
        "mask_rle": encode_mask(mask),
        "source_window": list(window),
        "mask_geometry_px": mapping(result.pixel_geometry),
        "box_px": list(result.pixel_bounds),
        "crown_geom": result.geometry.wkt,
    }
