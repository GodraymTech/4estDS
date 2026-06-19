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
from ..preprocess.slicing import build_quadtree, clamp_window



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
    *,
    target_size_fn=None,
    root_size: int = 1024,
    min_size: int = 256,
    conf_thr: float = 0.25,
    iou_thr: float = 0.55,
    batch_size: int = 8,
    overlap_px: int = 0,
    conf_type: str = "max",
    trunc_penalty: float = 0.5,
) -> InferenceResult:
    """对一幅影像跑完整的切片->推理->去重流程。

    image_source: 需有 width/height 属性,可选 read_window(x,y,w,h)。
    target_size_fn: (cx, cy) -> 期望切片边长;None 时为单一尺度(退化为均匀网格)。
    """
    width = int(image_source.width)
    height = int(image_source.height)
    if width <= 0 or height <= 0:
        log.warning("空影像: width=%d height=%d, 跳过推理", width, height)
        return InferenceResult(Detections([]), meta={"empty_image": True})

    t0 = time.perf_counter()
    log.info(
        "推理开始: 影像 %dx%d backend=%s root_size=%d overlap_px=%d conf_thr=%.2f iou_thr=%.2f conf_type=%s",
        width, height, getattr(detector, "name", "?"), root_size, overlap_px, conf_thr, iou_thr, conf_type,
    )

    if target_size_fn is None:
        target_size_fn = lambda cx, cy: root_size  # noqa: E731 单一尺度

    tiles = build_quadtree(width, height, target_size_fn, root_size, min_size)

    detector.ensure_loaded()
    # 先收集有效读窗坐标(裁到边界、跳过空窗)
    # overlap_px>0 时向四周外扩读窗(仍裁到图边),让跨边界的树在相邻 tile 中完整出现,
    # 交由 WBF 去重(解决非重叠网格的边界重复检出)。
    coords: list[tuple[int, int, int, int]] = []
    skipped = 0
    ov = max(0, int(overlap_px))
    for tile in tiles:
        x, y, w, h = clamp_window(tile.x, tile.y, tile.size, width, height)
        if w <= 0 or h <= 0:
            skipped += 1
            continue
        if ov > 0:
            nx, ny = max(0, x - ov), max(0, y - ov)
            nx2, ny2 = min(width, x + w + ov), min(height, y + h + ov)
            x, y, w, h = nx, ny, nx2 - nx, ny2 - ny
        coords.append((x, y, w, h))

    log.info(
        "切片清单: 生成 %d tile, 有效读窗 %d, 跳过空窗 %d (overlap_px=%d)",
        len(tiles), len(coords), skipped, ov,
    )

    read = getattr(image_source, "read_window", None)
    global_items: list[Detection] = []
    processed = 0
    bs = max(1, batch_size)
    # 分批推理:每批只读取该批读窗像素,内存占用以 batch_size 为界
    for i in range(0, len(coords), bs):
        chunk = coords[i : i + bs]
        windows = [
            Window(
                x=x, y=y, w=w, h=h,
                pixels=read(x, y, w, h) if callable(read) else None,
            )
            for (x, y, w, h) in chunk
        ]
        for win, dets in zip(windows, detector.predict_batch(windows)):
            for d in dets.filter_score(conf_thr).items:
                # 在读窗内部坐标判断是否触及“内部边界”(非图像边缘)->可能被切断
                trunc = (
                    (d.x1 <= 1.0 and win.x > 0)
                    or (d.y1 <= 1.0 and win.y > 0)
                    or (d.x2 >= win.w - 1.0 and win.x + win.w < width)
                    or (d.y2 >= win.h - 1.0 and win.y + win.h < height)
                )
                gd = d.offset(win.x, win.y)
                gd.extra = {**gd.extra, "truncated": bool(trunc)}
                global_items.append(gd)
            processed += 1

    raw_count = len(global_items)
    # 标签感知 + 权重感知 WBF:截断框降权(完整框主导融合坐标),保留物种标签
    boxes = [d.as_box() for d in global_items]
    scores = [d.score for d in global_items]
    labels = [d.label for d in global_items]
    weights = [
        d.score * (trunc_penalty if d.extra.get("truncated") else 1.0)
        for d in global_items
    ]
    fused_boxes = fuse(
        boxes, scores,
        labels=labels, weights=weights,
        iou_thr=iou_thr, conf_type=conf_type,
    )
    fused = Detections(
        [
            Detection(
                x1=f.box[0], y1=f.box[1], x2=f.box[2], y2=f.box[3],
                score=f.score, label=f.label, extra={"support": f.support},
            )
            for f in fused_boxes
        ],
        {"backend": getattr(detector, "name", "?"), "fusion": "wbf"},
    )
    elapsed = time.perf_counter() - t0
    dedup = (1 - len(fused) / raw_count) * 100 if raw_count else 0.0
    log.info(
        "推理完成: tiles=%d 处理=%d 跳空=%d 原始框=%d 融合后=%d 去重率=%.1f%% 耗时=%.2fs",
        len(tiles), processed, skipped, raw_count, len(fused), dedup, elapsed,
    )
    return InferenceResult(
        detections=fused,
        tiles_total=len(tiles),
        tiles_processed=processed,
        tiles_skipped_empty=skipped,
        raw_count=raw_count,
        fused_count=len(fused),
        meta={"width": width, "height": height},
    )
