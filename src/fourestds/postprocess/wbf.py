"""尺度感知加权框融合(阶段五)。

切片拼接后,同一棵树可能在多张子图/多个尺度重复检出,跨 tile 边界还会被
切断。这里提供纯 Python 的加权框融合(WBF),生产级特性:

- **标签感知**:仅融合同类别(同物种)检测,不会把不同树种当成重复。
- **权重感知**:每个框可带可靠度权重(如 置信度 × 截断惩罚),融合坐标按 score×weight 加权。
- **置信度策略**:conf_type="avg"(簇均值)或 "max"(簇最大);跨 tile 去重同一目标
  宜用 max。
- **边界拼合**:可选 center_merge_frac,把低 IoU 但中心极近的框归为同棵
  (补捉被 tile 边界切半的重复)。
纯 Python,可单测。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

Box = tuple[float, float, float, float]


def iou(a: Box, b: Box) -> float:
    """两个框 (x1,y1,x2,y2) 的交并比。"""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _center(b: Box) -> tuple[float, float]:
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def _diag(b: Box) -> float:
    return math.hypot(b[2] - b[0], b[3] - b[1])


@dataclass
class FusedBox:
    """一个融合后的框。support 为簇内成员数(多视角一致性的信号)。"""
    box: Box
    score: float
    label: str = "tree"
    support: int = 1
    extra: dict = field(default_factory=dict)


def fuse(
    boxes: list[Box],
    scores: list[float],
    *,
    labels: list[str] | None = None,
    weights: list[float] | None = None,
    iou_thr: float = 0.55,
    conf_type: str = "avg",
    center_merge_frac: float = 0.0,
) -> list[FusedBox]:
    """标签/权重感知的 WBF。按得分降序贪婪聚簇,簇内按 score×weight 加权平均坐标。

    labels:  每框标签(默认全 "tree");仅同标签可融合。
    weights: 每框可靠度权重(默认 1.0)。
    conf_type: "avg" 簇均值 | "max" 簇最大。
    center_merge_frac: >0 时,中心距离 ≤ frac×min(对角线) 的同标签框也归为同簇。
    """
    n = len(boxes)
    if n == 0:
        return []
    labels = list(labels) if labels is not None else ["tree"] * n
    weights = list(weights) if weights is not None else [1.0] * n
    order = sorted(range(n), key=lambda i: scores[i], reverse=True)
    used = [False] * n
    out: list[FusedBox] = []
    for i in order:
        if used[i]:
            continue
        used[i] = True
        cluster = [i]
        for j in order:
            if used[j] or labels[j] != labels[i]:
                continue
            merged = iou(boxes[i], boxes[j]) >= iou_thr
            if not merged and center_merge_frac > 0.0:
                d = math.dist(_center(boxes[i]), _center(boxes[j]))
                ref = min(_diag(boxes[i]), _diag(boxes[j])) or 1.0
                merged = d <= center_merge_frac * ref
            if merged:
                used[j] = True
                cluster.append(j)
        ws = [max(1e-9, scores[k] * weights[k]) for k in cluster]
        wsum = sum(ws)
        fb = tuple(
            sum(boxes[k][c] * ws[idx] for idx, k in enumerate(cluster)) / wsum
            for c in range(4)
        )
        if conf_type == "max":
            sc = max(scores[k] for k in cluster)
        else:
            sc = sum(scores[k] for k in cluster) / len(cluster)
        out.append(
            FusedBox(box=fb, score=sc, label=labels[i], support=len(cluster))
        )
    return out


def weighted_boxes_fusion(
    boxes: list[Box],
    scores: list[float],
    iou_thr: float = 0.55,
) -> tuple[list[Box], list[float]]:
    """向后兼容包装:返回 (fused_boxes, fused_scores)。内部调用 fuse(conf_type="avg")。"""
    fused = fuse(boxes, scores, iou_thr=iou_thr, conf_type="avg")
    return [f.box for f in fused], [f.score for f in fused]
