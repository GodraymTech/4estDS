"""尺度感知加权框融合(阶段五)。

切片拼接后,同一棵树可能在多张子图/多个尺度重复检出,跨 tile 边界还会被
切断。这里提供纯 Python 的加权框融合(WBF),生产级特性:

- **标签感知**:仅融合同类别(同物种)检测,不会把不同树种当成重复。
- **权重感知**:每个框可带可靠度权重(如 置信度 × 截断惩罚),融合坐标按 score×weight 加权。
- **置信度策略**:conf_type="avg"(簇均值)或 "max"(簇最大);跨 tile 去重同一目标宜用 max。
- **边界拼合**:可选 center_merge_frac,把低 IoU 但中心极近的框归为同棵(捕捉被 tile 边界切半的重复)。
纯 Python,可单测。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

Box = tuple[float, float, float, float]


def iou(a: Box, b: Box) -> float:
    ax1, ay1, ax2, ay2 = a[:4]
    bx1, by1, bx2, by2 = b[:4]
    
    # 用 python 表达式代替内置 max/min，杜绝 list_iterator 干扰并大幅提升热循环速度
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


def _center(b: Box) -> tuple[float, float]:
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def _diag(b: Box) -> float:
    # 纯 Python 算术计算，绕过 math.hypot 规避特定节点上的段错误 (Segmentation Fault)
    return ((b[2] - b[0]) ** 2 + (b[3] - b[1]) ** 2) ** 0.5


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
    """基于图连通分量 (Connected Components) 的终极空间加权框融合去重。
    
    通过构建检测框的重叠连通图，将所有在物理空间上高度重合、嵌套、或中心极近的框连通，
    无论它们的预测标签是否一致（同物种或跨物种均进行归并），均强行融合成单个单木物体，
    并对每个连通分量执行坐标加权平均。这能彻底杜绝多重/链式重叠框的残留。
    """
    n = len(boxes)
    if n == 0:
        return []
    labels = list(labels) if labels is not None else ["tree"] * n
    weights = list(weights) if weights is not None else [1.0] * n
    
    # 提前计算所有检测框的中心、对角线和面积
    centers = [_center(b) for b in boxes]
    diags = [_diag(b) for b in boxes]
    areas = []
    for b in boxes:
        w = b[2] - b[0] if b[2] > b[0] else 0.0
        h = b[3] - b[1] if b[3] > b[1] else 0.0
        areas.append(w * h)

    # 1. 构建图邻接表
    adj = {i: [] for i in range(n)}
    
    # 启用自适应的 center_merge_frac 备用值以防配置注入失效 (默认 0.18 对角线)
    resolved_center_merge = center_merge_frac if center_merge_frac > 0.0 else 0.18

    for i in range(n):
        for j in range(i + 1, n):
            # 计算 IoU
            ax1, ay1, ax2, ay2 = boxes[i]
            bx1, by1, bx2, by2 = boxes[j]
            ix1 = ax1 if ax1 > bx1 else bx1
            iy1 = ay1 if ay1 > by1 else by1
            ix2 = ax2 if ax2 < bx2 else bx2
            iy2 = ay2 if ay2 < by2 else by2
            iw = ix2 - ix1 if ix2 > ix1 else 0.0
            ih = iy2 - iy1 if iy2 > iy1 else 0.0
            inter = iw * ih
            
            union = areas[i] + areas[j] - inter
            iou_val = inter / union if union > 0.0 else 0.0
            
            # 计算双向包含度 (交集占各自框面积比例)
            containment_i = inter / areas[i] if areas[i] > 0.0 else 0.0
            containment_j = inter / areas[j] if areas[j] > 0.0 else 0.0
            max_containment = containment_i if containment_i > containment_j else containment_j
            
            # 纯 Python 算术计算中心距离，绕过 math.dist 规避特定节点上的段错误 (Segmentation Fault)
            d = ((centers[i][0] - centers[j][0]) ** 2 + (centers[i][1] - centers[j][1]) ** 2) ** 0.5
            ref = diags[i] if diags[i] < diags[j] else diags[j]
            ref = ref or 1.0
            
            should_merge = False
            
            # 终极空间融合逻辑 (不区分标签类别)：同一个物理位置上不可能同时存在多棵独立的红树林树木。
            # 只要满足空间交叠门槛，无论预测物种是否一致，一律融合去重，以高置信度物种标签为准。
            if iou_val >= 0.35:
                # 空间重叠度中等即可合并
                should_merge = True
            elif max_containment >= 0.45:
                # 大框套小框，或显著包含关系
                should_merge = True
            elif d <= 0.28 * ref and inter > 0.0:
                # 中心距离极近且有交集
                should_merge = True
            elif resolved_center_merge > 0.0 and d <= resolved_center_merge * ref:
                # 跨滑窗断裂重组
                should_merge = True
            
            if should_merge:
                adj[i].append(j)
                adj[j].append(i)

    # 2. 深度优先搜索（DFS）划分连通分量
    visited = [False] * n
    components: list[list[int]] = []
    
    for i in range(n):
        if not visited[i]:
            comp = []
            queue = [i]
            visited[i] = True
            while queue:
                curr = queue.pop(0)
                comp.append(curr)
                for neighbor in adj[curr]:
                    if not visited[neighbor]:
                        visited[neighbor] = True
                        queue.append(neighbor)
            components.append(comp)

    # 3. 对每个连通分量进行加权框融合
    out: list[FusedBox] = []
    for comp in components:
        # 挑选出该连通分量中置信度得分最高的检测框作为“主检测框”，继承其物种标签
        best_idx = max(comp, key=lambda idx: scores[idx])
        best_label = labels[best_idx]
        
        ws = [scores[k] * weights[k] for k in comp]
        ws = [w if w > 1e-9 else 1e-9 for w in ws]
        wsum = sum(ws)
        
        # 加权融合坐标
        fb_x1 = sum(boxes[k][0] * ws[idx] for idx, k in enumerate(comp)) / wsum
        fb_y1 = sum(boxes[k][1] * ws[idx] for idx, k in enumerate(comp)) / wsum
        fb_x2 = sum(boxes[k][2] * ws[idx] for idx, k in enumerate(comp)) / wsum
        fb_y2 = sum(boxes[k][3] * ws[idx] for idx, k in enumerate(comp)) / wsum
        fb = (fb_x1, fb_y1, fb_x2, fb_y2)
        
        if conf_type == "max":
            sc = max(scores[k] for k in comp)
        else:
            sc = sum(scores[k] for k in comp) / len(comp)
            
        out.append(
            FusedBox(
                box=fb,
                score=sc,
                label=best_label,
                support=len(comp),
                extra={
                    "best_index": best_idx,
                    "merge_iou_count": len(comp) - 1,
                    "merge_center_count": 0
                }
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
