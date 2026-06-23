"""切片清单推理编排器(阶段三)。

流程:
  1) 用创新点 A 的四叉树生成 tile 清单(纯几何,查 size_map 表)。
  2) 逐 tile: clamp_window 裁到边界 -> 跳空读窗 -> 检测器推理(读窗内部坐标)。
  3) detections.offset(x, y) 回写全图坐标。
  4) 全图 WBF 去重(跨 tile / 跨尺度重复检出)。

设计要点(中间产物谨慎):不落地裁切图片;读窗按需从 image_source 取像素。
mock 后端不需像素,可在无 GPU/无网环境端到端验证。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..detect.base import BaseDetector, Detection, Detections, Window
from loguru import logger as log
from ..postprocess.wbf import fuse
from ..preprocess.slicing import generate_slice_windows


@dataclass(frozen=True)
class InferenceConfig:
    """推理超参数配置封装对象。"""
    root_size: int = 1024
    min_size: int = 256
    conf_thr: float = 0.25
    iou_thr: float = 0.55
    batch_size: int = 8
    overlap_rate: float = 0.2
    conf_type: str = "max"
    trunc_penalty: float = 0.5
    center_merge_frac: float = 0.0

    @classmethod
    def from_settings(
        cls,
        settings,
        tile_size: int | None = None,
        overlap_rate: float | None = None,
    ) -> InferenceConfig:
        """从系统配置中安全构建 InferenceConfig，支持显式参数覆盖。"""
        ov = overlap_rate if overlap_rate is not None else float(settings.get("preprocess.slice.default_overlap", 0.2))
        sz = tile_size if tile_size is not None else int(settings.get("root_size", 1024))
        return cls(
            root_size=sz,
            min_size=int(settings.get("min_size", 256)),
            conf_thr=float(settings.get("detect.conf_threshold", 0.25)),
            iou_thr=float(settings.get("detect.iou_threshold", 0.55)),
            batch_size=int(settings.get("detect.batch_size", 8)),
            overlap_rate=ov,
            conf_type=str(settings.get("postprocess.conf_type", "max")),
            trunc_penalty=float(settings.get("postprocess.trunc_penalty", 0.5)),
            center_merge_frac=float(settings.get("postprocess.center_merge_frac", 0.0)),
        )


@dataclass
class InferenceResult:
    detections: Detections
    tiles_total: int = 0
    tiles_processed: int = 0
    tiles_skipped_empty: int = 0
    raw_count: int = 0
    fused_count: int = 0
    meta: dict = field(default_factory=dict)


def run_inference(
    image_source,
    detector: BaseDetector,
    config: InferenceConfig,
) -> InferenceResult:
    """对一幅影像执行切片->推理->去重全流程（引擎核心）。

    image_source: 统一的 ImageSource 适配器实例。
    detector: 模型检测器。
    config: 显式注入的 InferenceConfig。
    """
    width = int(image_source.width)
    height = int(image_source.height)
    if width <= 0 or height <= 0:
        log.warning("空影像: width={} height={}, 跳过推理", width, height)
        return InferenceResult(Detections([]), meta={"empty_image": True})

    t0 = time.perf_counter()
    log.info(
        "【推理内核启动】 影像={}x{} backend={} root_size={} overlap_rate={:.0%} conf_thr={:.2f} iou_thr={:.2f} conf_type={}",
        width, height, getattr(detector, "name", "?"), config.root_size, config.overlap_rate, config.conf_thr, config.iou_thr, config.conf_type,
    )

    # 1. 规则切片网格生成，支持自定义数据源的自定义窗口列表（针对已落盘切片）
    if hasattr(image_source, "get_slice_windows") and callable(image_source.get_slice_windows):
        coords = image_source.get_slice_windows()
        log.info("【切片网格】从物理瓦片源载入已存切片清单，共包含 {} 个瓦片", len(coords))
    else:
        coords = generate_slice_windows(width, height, config.root_size, config.overlap_rate)
        log.info("【切片网格】已生成动态切片窗口清单，共包含 {} 个瓦片", len(coords))

    detector.ensure_loaded()
    read = getattr(image_source, "read_window", None)
    global_items: list[Detection] = []
    processed = 0
    bs = max(1, config.batch_size)
    
    total_raw_predicts = 0
    from ..utils.progress import track_progress
    
    # 2. 分批调度前向推理
    chunks = [coords[i : i + bs] for i in range(0, len(coords), bs)]
    for chunk in track_progress(chunks, desc="动态读窗推理中"):
        windows = []
        for (x, y, w, h) in chunk:
            pixels = read(x, y, w, h) if callable(read) else None
            win = Window(x=x, y=y, w=w, h=h, pixels=pixels)
            # 记录瓦片的源文件路径（主要针对物理瓦片，方便溯源）
            if hasattr(image_source, "_coord_to_file"):
                fpath = image_source._coord_to_file.get((x, y, w, h))
                if fpath:
                    win.source_subimage_path = str(fpath)
            if not getattr(win, "source_subimage_path", None):
                win.source_subimage_path = f"Window_{x}_{y}_{w}_{h}"
            windows.append(win)

        for win, dets in zip(windows, detector.predict_batch(windows)):
            total_raw_predicts += len(dets)
            filtered_dets = dets.filter_score(config.conf_thr).items
            log.debug("滑窗 (x={}, y={}, w={}, h={}) 模型原始预测数: {}, 置信度过滤数: {}", win.x, win.y, win.w, win.h, len(dets), len(filtered_dets))
            for d in filtered_dets:
                # 判断是否触及“内部边界”(非图像边缘)->可能被切断，作截断标记以备后处理降权
                trunc = (
                    (d.x1 <= 1.0 and win.x > 0)
                    or (d.y1 <= 1.0 and win.y > 0)
                    or (d.x2 >= win.w - 1.0 and win.x + win.w < width)
                    or (d.y2 >= win.h - 1.0 and win.y + win.h < height)
                )
                gd = d.offset(win.x, win.y)
                gd.extra = {
                    **gd.extra,
                    "truncated": bool(trunc),
                    "box_px_sub": [d.x1, d.y1, d.x2, d.y2],
                    "source_subimage_path": win.source_subimage_path
                }
                global_items.append(gd)
            processed += 1

    raw_count = len(global_items)

    # 显式清理并销毁推理阶段残留的大像素数组和数据源句柄，预防底层 C++ 库（PyTorch / GDAL / rasterio）发生 GC 时内存重叠段错误
    if "chunks" in locals():
        del chunks
    if "windows" in locals():
        del windows
    
    if hasattr(image_source, "close") and callable(image_source.close):
        try:
            image_source.close()
        except Exception:
            pass

    import gc
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass
    
    # 3. 加权框去重融合 (WBF)
    log.info("【WBF去重融合】开始对 {} 个置信度过滤后的检测框执行加权框融合去重...", raw_count)
    boxes = [d.as_box() for d in global_items]
    scores = [d.score for d in global_items]
    labels = [d.label for d in global_items]
    weights = [
        d.score * (config.trunc_penalty if d.extra.get("truncated") else 1.0)
        for d in global_items
    ]
    fused_boxes = fuse(
        boxes, scores,
        labels=labels, weights=weights,
        iou_thr=config.iou_thr, conf_type=config.conf_type,
        center_merge_frac=config.center_merge_frac,
    )
    fused = Detections(
        [
            Detection(
                x1=f.box[0], y1=f.box[1], x2=f.box[2], y2=f.box[3],
                score=f.score, label=f.label,
                extra={
                    "support": f.support,
                    **global_items[f.extra["best_index"]].extra
                },
            )
            for f in fused_boxes
        ],
        {"backend": getattr(detector, "name", "?"), "fusion": "wbf"},
    )
    elapsed = time.perf_counter() - t0
    total_iou_merged = sum(f.extra.get("merge_iou_count", 0) for f in fused_boxes)
    total_center_merged = sum(f.extra.get("merge_center_count", 0) for f in fused_boxes)

    log.info(
        "【推理内核完成】 滑窗处理数: {}/{}，耗时: {:.2f}s",
        processed, len(coords), elapsed,
    )
    log.info(
        "【去重统计】 原始检测框数 {} -> 置信度过滤后({}) {} -> WBF去重-IoU融合后: {} -> WBF去重-中心距离融合后: {}",
        total_raw_predicts, config.conf_thr, raw_count,
        raw_count - total_iou_merged, len(fused)
    )
    return InferenceResult(
        detections=fused,
        tiles_total=len(coords),
        tiles_processed=processed,
        tiles_skipped_empty=0,
        raw_count=raw_count,
        fused_count=len(fused),
        meta={"width": width, "height": height, "tile_size": config.root_size},
    )
