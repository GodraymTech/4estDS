"""4estDS 系统工具集（命令行 tool 支持）。"""
from __future__ import annotations

from importlib import import_module

__all__ = [
    "draw_bbox_main",
    "draw_dsm_main",
    "draw_las_main",
    "get_image_dimensions",
    "standardize_ds",
    "crop_tiff_main",
    "parse_voc_file",
    "parse_yolo_file",
    "parse_geojson_file",
]

_PUBLIC_EXPORTS = {
    "draw_bbox_main": (".draw_bbox", "draw_bbox_main"),
    "draw_dsm_main": (".draw_dsm", "draw_dsm_main"),
    "draw_las_main": (".draw_las", "draw_las_main"),
    "get_image_dimensions": (".image", "get_image_dimensions"),
    "standardize_ds": (".standardize_dataset", "standardize_ds"),
    "crop_tiff_main": (".crop_tiff", "crop_tiff_main"),
    "parse_voc_file": (".annotations", "parse_voc_file"),
    "parse_yolo_file": (".annotations", "parse_yolo_file"),
    "parse_geojson_file": (".annotations", "parse_geojson_file"),
}


def __getattr__(name: str):
    try:
        module_name, attribute_name = _PUBLIC_EXPORTS[name]
    except KeyError as error:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from error

    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
