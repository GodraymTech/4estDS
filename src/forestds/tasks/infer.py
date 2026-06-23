"""单图推理任务编排（tasks 层）。

把 CLI 的 ``cmd_infer`` 里的所有业务流程提取至此，实现：
- CLI 层只做"参数解析 + 调本函数 + 格式化结果"
- 本函数可被单测、批处理、SDK 直接调用，不依赖 typer
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger as log

from .. import paths

if TYPE_CHECKING:
    pass

# 导出格式合法枚举（供 CLI 参数校验引用）
VALID_EXPORT_FORMATS: tuple[str, ...] = ("geojson", "shp", "gpkg", "csv")


def run_infer_pipeline(
    image_path: str,
    *,
    run_id: str,
    settings,
    arch: str | None = None,
    acquisition_time: str | None = None,
    location: str | None = None,
    overlap_rate: float | None = None,
    chm: str | None = None,
    dsm: str | None = None,
    dem: str | None = None,
    las: str | None = None,
    las_grid_size: float | None = None,
    dem_default: float | None = None,
    draw_box: bool | None = None,
    export_fmt: str | None = None,
    detector=None,
) -> dict:
    """单图推理完整流水线。

    按顺序执行：
    1. 初始化检测器
    2. 影像推理（自动路由 物理切片/动态COG/直推模式）
    3. GIS 投影与地块登记
    4. 多源高程融合树高标注（可选）
    5. 观测数据入库
    6. 可视化绘图（可选）
    7. 推理报告生成
    8. 切片目录清理（keep_tiles=False 时）
    9. GIS 图层导出（export_fmt 指定时）

    Returns:
        metrics dict：{tiles_total, tiles_processed, tiles_skipped_empty,
                       raw_count, fused_count, observations_written,
                       tract_id, run_id, report_path, export_path}
    Raises:
        任何未被捕获的异常会冒泡到调用方（CLI / 单测）处理。
    """
    from ..db import writer
    from ..detect import get_detector

    arch_val = arch or settings.get("detect.arch", "ultralytics")
    db_url = settings.get("url", None)

    # 导出格式：显式参数 > 配置文件 default_format > None（不导出）
    resolved_export_fmt = export_fmt or settings.get("export.default_format") or None
    if resolved_export_fmt:
        resolved_export_fmt = resolved_export_fmt.lower().strip()
        if resolved_export_fmt not in VALID_EXPORT_FORMATS:
            raise ValueError(
                f"不支持的导出格式 '{resolved_export_fmt}'，可选: {', '.join(VALID_EXPORT_FORMATS)}"
            )

    # ── 1. 初始化检测器 ────────────────────────────────────────────────────────
    if detector is None:
        detector = get_detector(
            arch_val,
            weights=settings.get(f"detect.models.{arch_val}.weights", settings.get("detect.weights")),
            conf=float(settings.get("detect.conf_threshold", 0.25)),
            iou=float(settings.get("detect.iou_threshold", 0.6)),
            imgsz=int(settings.get("model_input", 1024)),
            device=settings.get("device", None),
            verbose=settings.get("detect.verbose", False),
        )

    # ── 2. 核心推理 ────────────────────────────────────────────────────────────
    t0 = time.time()
    from ..preprocess import prepare_inference_image
    from ..engine import InferenceConfig, run_inference
    from ..engine.sources import RasterImageSource, InMemorySource, TiledDirectorySource
    from PIL import Image
    import numpy as np

    # 2.1 委托预处理模块执行所有前置逻辑 (读尺寸、检查COG、自适应寻优、静态切片落盘)
    slice_action = settings.get("preprocess.slice.action", "slice")
    seed_window_size = int(settings.get("preprocess.slice.scope.seed_window_size", 2560))
    prep = prepare_inference_image(
        image_path=image_path,
        slice_action=slice_action,
        seed_window_size=seed_window_size,
        overlap_rate=overlap_rate,
        settings=settings,
        run_id=run_id,
        detector=detector,
    )
    
    width = prep["width"]
    height = prep["height"]
    mode = prep["mode"]
    tiles_dir = prep["tiles_dir"]
    image_path = prep["image_path"]

    # 2.2 构造显式 InferenceConfig 超参数配置，注入自标定（SCOPE）的最优参数
    config = InferenceConfig.from_settings(
        settings,
        tile_size=prep["tile_size"],
        overlap_rate=prep["overlap_rate"],
    )

    # 2.3 路由并初始化对应的影像源适配器 (ImageSource)
    if mode == "physical_slice":
        log.info("【模式路由】-->「静态切片落盘推理模式」，切片目录为: {}", tiles_dir)
        source = TiledDirectorySource(tiles_dir, width, height)
    elif mode == "on_the_fly":
        log.info("【模式路由】-->「COG 动态滑窗推理模式」，影像为: {}", image_path)
        source = RasterImageSource(image_path)
    else:
        log.info("【模式路由】-->「整图直接推理模式」，影像为: {}", image_path)
        with Image.open(image_path) as img:
            pixels = np.asarray(img.convert("RGB"))
        source = InMemorySource(pixels)

    try:
        result = run_inference(source, detector, config)
    finally:
        source.close()

    # 2.4 为了跟以前的返回值元数据兼容，将 tiles_dir 相对于 home_dir() 记录到 meta 中
    if mode == "physical_slice" and tiles_dir:
        try:
            rel_tiles_dir = str(Path(tiles_dir).relative_to(paths.home_dir()))
        except Exception:
            rel_tiles_dir = str(tiles_dir)
        result.meta["tiles_dir"] = rel_tiles_dir

    # ── 3. GIS 投影 & 地块登记 ─────────────────────────────────────────────────
    from ..geo import compute_tract_geometry
    transform_obj = crs_obj = None
    tiff_date = tiff_ul = None
    if image_path.lower().endswith((".tif", ".tiff")):
        try:
            import rasterio
            with rasterio.open(image_path) as src:
                transform_obj = src.transform
                crs_obj = src.crs
                
                # 尝试提取 TIFF 时间标签
                tags = src.tags()
                date_candidates = [
                    tags.get("TIFFTAG_DATETIME"),
                    tags.get("DateTime"),
                    tags.get("datetime"),
                ]
                for c in date_candidates:
                    if c and isinstance(c, str):
                        digits = "".join(filter(str.isdigit, c))
                        if len(digits) >= 8:
                            tiff_date = digits[:8]
                            break
                
                # 提取左上角地理坐标作为位置候选
                if crs_obj and transform_obj:
                    x_ul, y_ul = transform_obj * (0, 0)
                    tiff_ul = f"UL_{x_ul:.4f}_{y_ul:.4f}"
        except Exception:
            pass

    # 如果无法从 TIFF tag 中读取时间，尝试读取文件修改时间作为备选
    if not tiff_date:
        try:
            import os
            import datetime
            mtime = os.path.getmtime(image_path)
            tiff_date = datetime.datetime.fromtimestamp(mtime).strftime("%Y%m%d")
        except Exception:
            pass

    geo = compute_tract_geometry(
        image_path, result.meta.get("width"), result.meta.get("height"),
        transform=transform_obj, crs=crs_obj,
    ) or {}
    if not geo:
        log.warning(
            "输入图像未包含地理空间元数据，地理面积/林木密度等指标在报告和 DB 中将缺失。"
        )

    final_acquisition_time = acquisition_time or tiff_date or "000000"
    final_location = location or tiff_ul or "default"

    tract_id = writer.ensure_tract(
        final_acquisition_time,
        final_location,
        name=Path(image_path).stem,
        pixel_w=geo.get("pixel_w") or result.meta.get("width"),
        pixel_h=geo.get("pixel_h") or result.meta.get("height"),
        gsd=geo.get("gsd"),
        geo_area=geo.get("geo_area"),
        area_unit=geo.get("area_unit"),
    )

    # ── 4. 高程融合树高（可选）────────────────────────────────────────────────
    if chm or dsm or las:
        from ..fusion import build_chm_sampler
        from ..geo import resolve_geo
        rgb_geo = resolve_geo(image_path, transform=transform_obj, crs=crs_obj)
        sampler = build_chm_sampler(
            chm_path=chm, dsm_path=dsm, dem_path=dem, las_path=las,
            las_grid_size=las_grid_size or float(settings.get("fusion.las_grid_size", settings.get("las_grid_size", 0.05))),
            dem_default_value=dem_default if dem_default is not None else float(settings.get("fusion.dem_default", settings.get("dem_default", 0.0))),
            rgb_geo=rgb_geo,
            stat=str(settings.get("fusion.height_stat", settings.get("height_stat", "max"))),
            volume_method=str(settings.get("fusion.volume_method", settings.get("volume_method", "cbh"))),
            cbh_factor=float(settings.get("fusion.cbh_factor", settings.get("cbh_factor", 0.3))),
            voxel_size=float(settings.get("fusion.voxel_size", settings.get("voxel_size", 0.2))),
        )
        if sampler is not None:
            sampler.annotate(result.detections)
            for _stype, _path in (("chm", chm), ("dsm", dsm), ("dem", dem), ("las", las)):
                if _path:
                    writer.register_source(tract_id, _stype, _path)

    # ── 5. 观测入库 ────────────────────────────────────────────────────────────
    written = writer.write_observations(
        tract_id, run_id, result.detections,
        slice_size=result.meta.get("tile_size"),
        image_path=image_path, transform=transform_obj, crs=crs_obj,
    )

    # ── 6. 可视化绘图（可选）──────────────────────────────────────────────────
    vis_path: str | None = None
    do_draw = draw_box if draw_box is not None else settings.get("postprocess.draw_box", False)
    if do_draw:
        from ..export.visualize import draw_detections_on_image
        vis_out = paths.outputs_infer_dir() / f"{Path(image_path).stem}_detected.jpg"
        if draw_detections_on_image(image_path, result.detections, output_path=vis_out, max_draw_size=5000):
            vis_path = str(vis_out)
            log.info("给原图绘制检测框: {}", vis_path)

    # ── 7. 运行指标 & run_log 终态 ─────────────────────────────────────────────
    dur = time.time() - t0
    metrics = {
        "tiles_total": result.tiles_total,
        "tiles_processed": result.tiles_processed,
        "tiles_skipped_empty": result.tiles_skipped_empty,
        "raw_count": result.raw_count,
        "fused_count": result.fused_count,
        "observations_written": written,
    }
    writer.finish_run_log(run_id, "succeeded", metrics=metrics, duration_s=dur)

    # ── 8. 推理报告（自动生成，失败不阻断）────────────────────────────────────
    report_path: str | None = None
    try:
        from ..report import generate_report
        report_fmt = settings.get("report.format", "md")
        with_charts = settings.get("report.with_charts", True)
        rep = generate_report(
            tract_id=tract_id, run_id=run_id, fmt=report_fmt,
            out_dir=paths.outputs_infer_dir(), db_url=db_url,
            with_charts=with_charts,
            vis_path=vis_path,
        )
        report_path = rep["out_path"]
    except Exception as e:
        log.warning("自动生成报告失败: {}", e)

    # ── 9. 切片目录清理（keep_tiles=False 时删除全部文件，保留空目录）─────────
    tiles_dir = result.meta.get("tiles_dir")
    if not settings.get("postprocess.keep_tiles", True) and tiles_dir:
        _purge_tile_files(Path(tiles_dir))

    # ── 10. GIS 图层导出（指定格式时触发）────────────────────────────────────
    export_path: str | None = None
    if resolved_export_fmt:
        try:
            from ..export import export_tract_to_file
            exp = export_tract_to_file(
                tract_id=tract_id, run_id=run_id, fmt=resolved_export_fmt,
                out_path=paths.outputs_infer_dir() / "vectors", db_url=db_url,
            )
            export_path = exp["out_path"]
            if exp.get("fallback"):
                log.warning("导出降级: {}", exp["fallback"])
        except Exception as e:
            log.warning("GIS 导出失败（不影响推理结果）: {}", e)

    return {
        **metrics,
        "tract_id": tract_id,
        "run_id": run_id,
        "duration_s": dur,
        "report_path": report_path,
        "export_path": export_path,
        "vis_path": vis_path,
    }


def _purge_tile_files(td: Path) -> None:
    """删除切片目录下的全部内容，保留空目录（rmtree + mkdir，单次系统调用）。"""
    if not td.is_dir():
        return
    import shutil
    n = sum(1 for _ in td.iterdir())  # 统计删除数（仅用于日志）
    shutil.rmtree(td)
    td.mkdir()
    log.info("切片目录已清空（keep_tiles=False）: {} 项已删除，空目录保留。", n)
