"""尺度感知加权框融合(阶段五)。

切片拼接后,同一棵树可能在多张子图/多个尺度重复检出。这里提供一个纯 Python 的
加权框融合(WBF)基础实现(可单测)。尺度感知权重与跨尺度优先级作为 TODO 增强。

TODO(阶段五): 按尺度可靠度加权;跨 tile 边界去重;输出到 tree_observations。
"""
from __future__ import annotations

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


def weighted_boxes_fusion(
    boxes: list[Box],
    scores: list[float],
    iou_thr: float = 0.55,
) -> tuple[list[Box], list[float]]:
    """基础 WBF:按得分降序贪婪聚簇,簇内按得分加权平均坎标。

    返回 (fused_boxes, fused_scores)。纯 Python,可单测。
    """
    if not boxes:
        return [], []
    order = sorted(range(len(boxes)), key=lambda i: scores[i], reverse=True)
    used = [False] * len(boxes)
    fused_boxes: list[Box] = []
    fused_scores: list[float] = []
    for i in order:
        if used[i]:
            continue
        cluster = [i]
        used[i] = True
        for j in order:
            if used[j]:
                continue
            if iou(boxes[i], boxes[j]) >= iou_thr:
                cluster.append(j)
                used[j] = True
        wsum = sum(scores[k] for k in cluster)
        fx1 = sum(boxes[k][0] * scores[k] for k in cluster) / wsum
        fy1 = sum(boxes[k][1] * scores[k] for k in cluster) / wsum
        fx2 = sum(boxes[k][2] * scores[k] for k in cluster) / wsum
        fy2 = sum(boxes[k][3] * scores[k] for k in cluster) / wsum
        fused_boxes.append((fx1, fy1, fx2, fy2))
        fused_scores.append(wsum / len(cluster))
    return fused_boxes, fused_scores
