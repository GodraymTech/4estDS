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

from dataclasses import dataclass, field

from ..detect.base import BaseDetector, Detection, Detections, Window
from ..postprocess.wbf import weighted_boxes_fusion
from ..preprocess.slicing import build_quadtree, clamp_window


@dataclass
class SyntheticImageSource:
    """合成影像源(供 mock 端到端测试):只有尺寸,读窗返回 None。"""
    width: int
    height: int

    def read_window(self, x: int, y: int, w: int, h: int):
        return None  # mock 检测器不需像素


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
) -> InferenceResult:
    """对一幅影像跑完整的切片->推理->去重流程。

    image_source: 需有 width/height 属性,可选 read_window(x,y,w,h)。
    target_size_fn: (cx, cy) -> 期望切片边长;None 时为单一尺度(退化为均匀网格)。
    """
    width = int(image_source.width)
    height = int(image_source.height)
    if width <= 0 or height <= 0:
        return InferenceResult(Detections([]), meta={"empty_image": True})

    if target_size_fn is None:
        target_size_fn = lambda cx, cy: root_size  # noqa: E731 单一尺度

    tiles = build_quadtree(width, height, target_size_fn, root_size, min_size)

    detector.ensure_loaded()
    # 先收集有效读窗坐标(裁到边界、跳过空窗)
    coords: list[tuple[int, int, int, int]] = []
    skipped = 0
    for tile in tiles:
        x, y, w, h = clamp_window(tile.x, tile.y, tile.size, width, height)
        if w <= 0 or h <= 0:
            skipped += 1
            continue
        coords.append((x, y, w, h))

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
            kept = dets.filter_score(conf_thr)
            global_items.extend(kept.offset(win.x, win.y).items)
            processed += 1

    raw_count = len(global_items)
    boxes = [d.as_box() for d in global_items]
    scores = [d.score for d in global_items]
    fused_boxes, fused_scores = weighted_boxes_fusion(boxes, scores, iou_thr=iou_thr)
    fused = Detections(
        [
            Detection(x1=b[0], y1=b[1], x2=b[2], y2=b[3], score=s, label="tree")
            for b, s in zip(fused_boxes, fused_scores)
        ],
        {"backend": getattr(detector, "name", "?")},
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
