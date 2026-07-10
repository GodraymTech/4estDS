"""预处理业务流管道 (Pre-inference preparation)."""
from __future__ import annotations

from pathlib import Path

from loguru import logger as log

from .. import paths
from ..utils import get_image_dimensions
from .cog import TIFF_FORMAT_LABELS, inspect_tiff_format, is_tiff_tile_ready, prepared_cog_path
from .scope import run_scope_calibration
from .tiling import execute_slicing


def prepare_inference_image(
    image_path: str,
    *,
    slice_action: str | None = None,
    seed_window_size: int = 2560,
    tile_size: int | None = None,
    overlap_rate: float | None = None,
    settings=None,
    run_id: str = "preprocess",
    detector=None,
    out_dir: str | Path | None = None,
) -> dict:
    """完成推理前准备: 严格 COG 准备、路由决策、SCOPE 和可选静态切片。"""
    if settings is None:
        from ..config import load_settings

        settings = load_settings()

    path = Path(image_path)
    is_tiff = path.suffix.lower() in {".tif", ".tiff"}
    resolved_slice_action = slice_action or settings.get("preprocess.action", "dynamic")
    if resolved_slice_action not in {"static", "dynamic"}:
        raise ValueError(f"不支持的预处理动作: {resolved_slice_action}。可选: dynamic, static")

    width, height = get_image_dimensions(image_path)
    has_large_size = width > seed_window_size or height > seed_window_size
    is_cog = False
    cog_conversion: dict[str, str] | None = None

    if is_tiff:
        original_image_path = image_path
        source_status = inspect_tiff_format(image_path)
        prepared_path, prepared_status = prepared_cog_path(image_path)
        if is_tiff_tile_ready(prepared_status):
            image_path = str(prepared_path)
            path = prepared_path
            is_cog = True
            width, height = get_image_dimensions(image_path)
            has_large_size = width > seed_window_size or height > seed_window_size
            if image_path != original_image_path:
                cog_conversion = {
                    "source_path": original_image_path,
                    "cog_path": image_path,
                    "source_format": source_status,
                }
                log.info("推理输入已转换为 COG: {}", image_path)
            else:
                log.info("推理输入已是可瓦片读取 TIFF: path={} status={}", image_path, prepared_status)
        else:
            log.warning(
                "TIFF 无法准备为可瓦片读取格式，将降级到非 COG 路由: path={} status={}",
                image_path,
                TIFF_FORMAT_LABELS.get(prepared_status, prepared_status),
            )

    if has_large_size:
        if resolved_slice_action == "dynamic" and is_tiff and is_cog:
            mode = "on_the_fly"
        else:
            mode = "physical_slice"
    else:
        mode = "direct"

    found_cache_dir = None
    if mode == "physical_slice":
        try:
            from ..db import reader

            found_cache_dir = reader.find_cached_tiles(image_path, url=settings.get("url", None))
        except Exception as exc:  # noqa: BLE001
            log.warning("检索切片缓存失败: {}", exc)

    resolved_tile_size = tile_size
    resolved_overlap_rate = overlap_rate
    if mode != "direct" and resolved_tile_size is None and is_tiff and settings.get("preprocess.scope.enable", False):
        log.info("触发 SCOPE: 自动寻优切割尺寸...")
        if detector is not None:
            scope_detector = detector
        else:
            from ..detect import get_detector

            arch_val = settings.get("detect.arch", "ultralytics")
            weights_val = settings.get(f"detect.models.{arch_val}.weights", settings.get("detect.weights"))
            scope_detector = get_detector(
                arch_val,
                weights=weights_val,
                conf=float(settings.get("detect.conf_threshold", 0.25)),
                iou=float(settings.get("detect.iou_threshold", 0.6)),
                imgsz=int(settings.get("detect.model_input", settings.get("model_input", 1024))),
                device=settings.get("detect.device", settings.get("device", None)),
                verbose=settings.get("detect.verbose", True),
            )
        resolved_tile_size, resolved_overlap_rate = run_scope_calibration(
            image_path,
            scope_detector,
            settings,
            run_id=run_id,
        )
        log.debug(
            "SCOPE 自标定决策: tile_size={}px, overlap_rate={:.0%}",
            resolved_tile_size,
            resolved_overlap_rate,
        )

    if resolved_tile_size is None:
        resolved_tile_size = int(settings.get("preprocess.default_tile_size", 1024))
    if resolved_overlap_rate is None:
        resolved_overlap_rate = float(settings.get("preprocess.default_overlap_rate", 0.1))

    tiles_dir = None
    saved_count = 0
    if mode == "physical_slice":
        if found_cache_dir:
            tiles_dir = found_cache_dir
            saved_count = len(list(found_cache_dir.glob("*.*")))
        else:
            log.info("预处理模式: 「静态切片」. 执行落盘...")
            base_out = Path(out_dir) if out_dir is not None else paths.outputs_preprocess_dir()
            saved_count = execute_slicing(
                image_path=image_path,
                out_dir=base_out,
                tile_size=resolved_tile_size,
                overlap_rate=resolved_overlap_rate,
                run_id=run_id,
                save_quality=95,
            )
            if saved_count == 0:
                log.error("静态切片落盘失败，无可用瓦片")
                raise RuntimeError("slicing produced 0 tiles")

            tiles_dir = base_out / f"tiles__{path.stem}"
            try:
                from ..db import writer as _writer

                _writer.update_tiles_dir(run_id, tiles_dir, url=settings.get("url", None))
            except Exception as exc:  # noqa: BLE001
                log.warning("写入 tiles_dir 至 DB 失败（不影响推理）: {}", exc)

    return {
        "mode": mode,
        "width": width,
        "height": height,
        "is_tiff": is_tiff,
        "is_cog": is_cog,
        "cog_conversion": cog_conversion,
        "tile_size": resolved_tile_size,
        "overlap_rate": resolved_overlap_rate,
        "tiles_dir": tiles_dir,
        "saved_count": saved_count,
        "image_path": image_path,
    }
