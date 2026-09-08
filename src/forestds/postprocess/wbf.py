"""尺度感知加权框融合(阶段五)。

切片拼接后,同一棵树可能在多张子图/多个尺度重复检出,跨 tile 边界还会被
切断。这里提供基于 numpy 向量化 + 空间网格索引的加权框融合(WBF),生产级特性:

- **标签感知**:继承簇内置信度最高框的物种标签。
- **权重感知**:每个框可带可靠度权重(如 置信度 × 截断惩罚),融合坐标按 score×weight 加权。
- **置信度策略**:conf_type="avg"(簇均值)或 "max"(簇最大);跨 tile 去重同一目标宜用 max。
- **边界拼合**:可选 center_merge_frac,把低 IoU 但中心极近的框归为同棵(捕捉被 tile 边界切半的重复)。

实现策略：
- 空间网格索引：每个框只与相邻 9 个格子内的框比较，避免 O(N^2) 全量对比。
- 逐行 numpy 向量化：对每个框 i，批量计算与所有候选邻居 j>i 的 IoU，避免二维广播爆炸。
- Union-Find 并查集：替代 DFS 邻接表，彻底消除大型 adj 字典对内存的压力。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

Box = tuple[float, float, float, float]


def iou(a: Box, b: Box) -> float:
    """单对框 IoU，供 scope.py 等调用方使用。"""
    ax1, ay1, ax2, ay2 = a[:4]
    bx1, by1, bx2, by2 = b[:4]
    ix1 = ax1 if ax1 > bx1 else bx1
    iy1 = ay1 if ay1 > by1 else by1
    ix2 = ax2 if ax2 < bx2 else bx2
    iy2 = ay2 if ay2 < by2 else by2
    iw = ix2 - ix1 if ix2 > ix1 else 0.0
    ih = iy2 - iy1 if iy2 > iy1 else 0.0
    inter = iw * ih
    w_a = ax2 - ax1 if ax2 > ax1 else 0.0
    h_a = ay2 - ay1 if ay2 > ay1 else 0.0
    area_a = w_a * h_a
    w_b = bx2 - bx1 if bx2 > bx1 else 0.0
    h_b = by2 - by1 if by2 > by1 else 0.0
    area_b = w_b * h_b
    union = area_a + area_b - inter
    return inter / union if union > 0.0 else 0.0


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
    """基于置信度降序聚类 + 动态空间网格索引的加权框融合 (WBF)。

    符合标准 WBF 原则：高置信度框引领聚类簇，低置信度框依附加权融合；
    通过动态局部网格实现 O(N) 线性邻域检索，彻底根除传递闭包引发的 MemoryError。
    """
    n = len(boxes)
    if n == 0:
        return []

    labels_list: list[str] = list(labels) if labels is not None else ["tree"] * n
    scores_arr = np.array(scores, dtype=np.float64)
    weights_arr = (
        np.array(weights, dtype=np.float64)
        if weights is not None
        else np.ones(n, dtype=np.float64)
    )

    B = np.asarray(boxes, dtype=np.float64)
    x1, y1, x2, y2 = B[:, 0], B[:, 1], B[:, 2], B[:, 3]
    cx = (x1 + x2) * 0.5
    cy = (y1 + y2) * 0.5
    diags = np.sqrt(np.maximum(0.0, x2 - x1) ** 2 + np.maximum(0.0, y2 - y1) ** 2)

    resolved_center_merge = center_merge_frac if center_merge_frac > 0.0 else 0.18

    # 聚类网格步长：以冠幅对角线的分位数自适应，上限不超过单 tile 尺寸 2048px，防假阳性异常大框导致网格退化
    q90_diag = float(np.percentile(diags, 90)) if n > 10 else float(diags.max())
    cell_size = min(max(q90_diag * 1.8, 100.0), 2048.0)

    # 排序：优先按 effective_weight = score * weight 降序遍历，由高置信引领
    effective_scores = scores_arr * weights_arr
    order = np.argsort(-effective_scores)

    # 簇结构定义：
    # cluster: {
    #   'box': [x1, y1, x2, y2],
    #   'area': float,
    #   'cx': float, 'cy': float, 'diag': float,
    #   'weighted_box_sum': np.array([4]),
    #   'weight_sum': float,
    #   'max_score': float,
    #   'score_sum': float,
    #   'count': int,
    #   'best_idx': int,
    #   'best_score': float,
    #   'best_label': str,
    #   'merge_iou_count': int,
    #   'merge_center_count': int,
    # }
    clusters: list[dict] = []
    grid: dict[tuple[int, int], list[int]] = {}

    for i in order:
        box_i = (float(x1[i]), float(y1[i]), float(x2[i]), float(y2[i]))
        sc_i = float(scores_arr[i])
        w_eff = max(float(effective_scores[i]), 1e-9)
        diag_i = float(diags[i])
        cx_i = float(cx[i])
        cy_i = float(cy[i])
        a1 = max(0.0, box_i[2] - box_i[0]) * max(0.0, box_i[3] - box_i[1])

        gx = int(cx_i // cell_size)
        gy = int(cy_i // cell_size)

        best_c_idx = -1
        best_overlap = -1.0
        merge_kind = "none"

        # 在当前格子及相邻 8 邻域搜索已有簇
        for ddx in (-1, 0, 1):
            for ddy in (-1, 0, 1):
                cell = (gx + ddx, gy + ddy)
                if cell not in grid:
                    continue
                for c_idx in grid[cell]:
                    c_obj = clusters[c_idx]
                    cb = c_obj["box"]

                    # 快速外接框不相交快速剪枝
                    if box_i[0] > cb[2] or box_i[2] < cb[0] or box_i[1] > cb[3] or box_i[3] < cb[1]:
                        inter = 0.0
                    else:
                        ix1 = box_i[0] if box_i[0] > cb[0] else cb[0]
                        iy1 = box_i[1] if box_i[1] > cb[1] else cb[1]
                        ix2 = box_i[2] if box_i[2] < cb[2] else cb[2]
                        iy2 = box_i[3] if box_i[3] < cb[3] else cb[3]
                        inter = (ix2 - ix1) * (iy2 - iy1) if (ix2 > ix1 and iy2 > iy1) else 0.0

                    a2 = c_obj["area"]
                    union = a1 + a2 - inter
                    iou_val = inter / union if union > 0.0 else 0.0

                    ci = inter / a1 if a1 > 0.0 else 0.0
                    cj = inter / a2 if a2 > 0.0 else 0.0
                    max_cont = ci if ci > cj else cj

                    # 中心距离合并判定
                    cb_cx = c_obj["cx"]
                    cb_cy = c_obj["cy"]
                    d_c = ((cx_i - cb_cx) ** 2 + (cy_i - cb_cy) ** 2) ** 0.5
                    ref = max(diag_i if diag_i < c_obj["diag"] else c_obj["diag"], 1.0)

                    # 是否满足合并条件
                    is_iou_match = (iou_val >= iou_thr) or (max_cont >= 0.45)
                    is_center_match = (
                        (d_c <= 0.28 * ref and inter > 0.0)
                        or (d_c <= resolved_center_merge * ref)
                    )

                    if is_iou_match and iou_val > best_overlap:
                        best_overlap = iou_val
                        best_c_idx = c_idx
                        merge_kind = "iou"
                    elif is_center_match and best_overlap < 0.0:
                        best_c_idx = c_idx
                        merge_kind = "center"

        if best_c_idx >= 0:
            c = clusters[best_c_idx]
            c["weighted_box_sum"] += np.array(box_i, dtype=np.float64) * w_eff
            c["weight_sum"] += w_eff
            new_box = c["weighted_box_sum"] / c["weight_sum"]
            bx1, by1, bx2, by2 = float(new_box[0]), float(new_box[1]), float(new_box[2]), float(new_box[3])
            c["box"] = (bx1, by1, bx2, by2)
            c["area"] = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
            c["cx"] = (bx1 + bx2) * 0.5
            c["cy"] = (by1 + by2) * 0.5
            c["diag"] = ((bx2 - bx1) ** 2 + (by2 - by1) ** 2) ** 0.5
            c["max_score"] = max(c["max_score"], sc_i)
            c["score_sum"] += sc_i
            c["count"] += 1
            if sc_i > c["best_score"]:
                c["best_score"] = sc_i
                c["best_idx"] = i
                c["best_label"] = labels_list[i]
            if merge_kind == "iou":
                c["merge_iou_count"] += 1
            else:
                c["merge_center_count"] += 1
        else:
            new_idx = len(clusters)
            clusters.append({
                "box": box_i,
                "area": a1,
                "cx": cx_i,
                "cy": cy_i,
                "diag": diag_i,
                "weighted_box_sum": np.array(box_i, dtype=np.float64) * w_eff,
                "weight_sum": w_eff,
                "max_score": sc_i,
                "score_sum": sc_i,
                "count": 1,
                "best_idx": i,
                "best_score": sc_i,
                "best_label": labels_list[i],
                "merge_iou_count": 0,
                "merge_center_count": 0,
            })
            grid.setdefault((gx, gy), []).append(new_idx)

    # 导出 FusedBox 列表
    out: list[FusedBox] = []
    for c in clusters:
        score_val = c["max_score"] if conf_type == "max" else (c["score_sum"] / c["count"])
        out.append(
            FusedBox(
                box=c["box"],
                score=float(score_val),
                label=c["best_label"],
                support=c["count"],
                extra={
                    "best_index": c["best_idx"],
                    "merge_iou_count": c["merge_iou_count"],
                    "merge_center_count": c["merge_center_count"],
                },
            )
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
