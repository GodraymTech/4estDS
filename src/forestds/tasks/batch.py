"""带预处理的批量推理任务编排（tasks 层）。

提供：
- resolve_images: 扁平化且去重、排序的有效影像列表发现
- run_batch_pipeline: 带完整预处理（SCOPE/COG/物理切片）的串行批量推理，单图异常不阻断
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from loguru import logger as log

from ..logging_setup import new_run_id

# 支持的可处理影像后缀
_VALID_SUFFIXES = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}


@dataclass
class BatchItemSummary:
    path: str
    location: str
    status: str  # succeeded | failed
    run_id: str
    tract_id: str | None = None
    tree_count: int = 0
    raw_count: int = 0
    fused_count: int = 0
    report_path: str | None = None
    export_path: str | None = None
    error: str | None = None


@dataclass
class BatchSummary:
    items: list[BatchItemSummary] = field(default_factory=list)
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    total_trees: int = 0
    elapsed_s: float = 0.0


def resolve_images(inputs: list[str]) -> list[Path]:
    """解析输入参数列表（包含混合的文件/目录），寻找并过滤有效后缀的影像，去重并排序。"""
    resolved_paths: set[Path] = set()
    for item in inputs:
        p = Path(item)
        if not p.exists():
            log.warning("输入路径不存在: {}", item)
            continue
        if p.is_file():
            if p.suffix.lower() in _VALID_SUFFIXES:
                resolved_paths.add(p.resolve())
            else:
                log.warning("不支持的影像文件格式: {}", item)
        elif p.is_dir():
            for child in p.iterdir():
                if child.is_file() and child.suffix.lower() in _VALID_SUFFIXES:
                    resolved_paths.add(child.resolve())
    return sorted(resolved_paths)


def build_batch_location(path: Path, prefix: str | None, duplicate_index: int | None = None) -> str:
    """生成批量推理单图 location。

    未指定前缀时使用图像文件名 stem；指定前缀时把 stem 作为后缀，确保用户输入
    的地理标识在批量任务中成为“前缀”而非所有影像的同一个 location。
    """
    base = path.stem
    if prefix and prefix.strip():
        base = f"{prefix.strip()}_{base}"
    if duplicate_index is not None and duplicate_index > 1:
        base = f"{base}_{duplicate_index}"
    return base


def run_batch_pipeline(
    images: list[str],
    *,
    settings,
    arch: str | None = None,
    acquisition_time: str | None = None,
    location: str | None = None,
    tile_size: int | None = None,
    overlap_rate: float | None = None,
    chm: str | None = None,
    dsm: str | None = None,
    dem: str | None = None,
    las: str | None = None,
    las_grid_size: float | None = None,
    dem_default: float | None = None,
    draw_box: bool | None = None,
    export_fmt: str | None = None,
    publish: bool = False,
) -> BatchSummary:
    """带完整预处理与后处理的批量串行推理。

    在批处理外层初始化一次 Detector，多张影像串行执行 run_infer_pipeline。
    单张影像的异常予以捕获并生成 failed 记录，不中断后续的推理。
    """
    from ..db import writer
    from ..detect import get_detector
    from ..cancellation import check_cancelled
    from .infer import run_infer_pipeline
    from .. import paths

    t0 = time.time()
    valid_paths = resolve_images(images)
    summary = BatchSummary(total=len(valid_paths))

    if not valid_paths:
        log.warning("批量推理未找到任何有效的影像文件。")
        return summary

    arch_val = arch or settings.get("detect.arch", "ultralytics")
    
    # 在外层统一初始化 Detector，实现权重仅加载一次
    detector = get_detector(
        arch_val,
        weights=settings.get(f"detect.models.{arch_val}.weights", settings.get("detect.weights")),
        conf=float(settings.get("detect.conf_threshold", 0.25)),
        iou=float(settings.get("detect.iou_threshold", 0.6)),
        imgsz=int(settings.get("model_input", 1024)),
        device=settings.get("detect.device", settings.get("device", None)),
        verbose=settings.get("detect.verbose", False),
    )

    log.info("批量预处理推理启动：共 {} 张影像，使用模型：{}", len(valid_paths), arch_val)

    from ..utils.progress import track_progress

    stem_seen: dict[str, int] = {}

    for idx, path in track_progress(list(enumerate(valid_paths, 1)), desc="批量影像推理"):
        check_cancelled(None)
        image_str = str(path)
        location_key = path.stem if not location else f"{location.strip()}_{path.stem}"
        stem_seen[location_key] = stem_seen.get(location_key, 0) + 1
        curr_location = build_batch_location(path, location, stem_seen[location_key])
        run_id = new_run_id()
        paths.set_run_context(run_id, "infer")
        
        # 预先开启该图的 run_log，以便发生异常时有据可查
        writer.start_run_log(
            run_id, "infer", model_arch=arch_val, input_path=image_str,
            params={
                "arch": arch_val,
                "image": image_str,
                "acquisition_time": acquisition_time,
                "location": curr_location,
            },
            url=settings.get("url", None),
        )

        item = BatchItemSummary(path=image_str, location=curr_location, status="failed", run_id=run_id)

        try:
            log.info("【批量调度】[{}/{}] 开始推理影像: {}", idx, len(valid_paths), image_str)
            res = run_infer_pipeline(
                image_str,
                run_id=run_id,
                settings=settings,
                arch=arch_val,
                acquisition_time=acquisition_time,
                location=curr_location,
                tile_size=tile_size,
                overlap_rate=overlap_rate,
                chm=chm,
                dsm=dsm,
                dem=dem,
                las=las,
                las_grid_size=las_grid_size,
                dem_default=dem_default,
                draw_box=draw_box,
                export_fmt=export_fmt,
                detector=detector,
            )
            item.status = "succeeded"
            item.tract_id = res.get("tract_id")
            item.tree_count = res.get("fused_count", 0)
            item.raw_count = res.get("raw_count", 0)
            item.fused_count = res.get("fused_count", 0)
            item.report_path = res.get("report_path")
            item.export_path = res.get("export_path")

            summary.succeeded += 1
            summary.total_trees += item.tree_count
            if publish:
                try:
                    writer.promote_run(run_id, url=settings.get("url", None))
                except Exception as promote_err:
                    log.warning("批量推理发布失败，结果已入库但未激活: run_id={} {}", run_id, promote_err)
            log.info("【批量调度】[{}/{}] 推理成功: {} (单图检出单木数={})", idx, len(valid_paths), image_str, item.tree_count)
        except Exception as e:
            item.error = str(e)
            summary.failed += 1
            log.opt(exception=False).error("【批量调度】[{}/{}] 推理失败: {}，原因: {} — {}", idx, len(valid_paths), image_str, type(e).__name__, e)
        
        elapsed = time.time() - t0
        log.info(
            "【批量进度】[{}/{}] 累计耗时: {:.1f}s | 已成功: {} | 已失败: {}\n",
            idx, len(valid_paths), elapsed, summary.succeeded, summary.failed
        )
        summary.items.append(item)

    summary.elapsed_s = time.time() - t0
    log.info(
        "批量预处理推理完成：共 {}, 成功={}, 失败={}, 累计单木数={}, 耗时={:.1f}s",
        summary.total, summary.succeeded, summary.failed, summary.total_trees, summary.elapsed_s
    )
    return summary
