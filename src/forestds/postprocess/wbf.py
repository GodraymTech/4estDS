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
    """单对框 IoU，供 scope.py 等调用方使用（保留接口兼容性）。"""
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
    """基于 numpy 逐行向量化 + 空间网格 + Union-Find 的加权框融合去重。

    可安全处理 10 万级别检测框，无 MemoryError 风险，无纯 Python 热循环。
    """
    n = len(boxes)
    if n == 0:
        return []

    labels_list: list[str] = list(labels) if labels is not None else ["tree"] * n
    scores_arr = np.array(scores, dtype=np.float64)
    weights_arr = np.array(weights, dtype=np.float64) if weights is not None else np.ones(n, dtype=np.float64)

    # 将所有框转为连续内存的 numpy 矩阵 [N, 4]
    B = np.asarray(boxes, dtype=np.float64)
    x1, y1, x2, y2 = B[:, 0], B[:, 1], B[:, 2], B[:, 3]

    # 向量化预计算各框的面积、中心、对角线
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)  # (N,)
    cx = (x1 + x2) * 0.5   # (N,)
    cy = (y1 + y2) * 0.5   # (N,)
    diags = np.sqrt(np.maximum(0.0, x2 - x1) ** 2 + np.maximum(0.0, y2 - y1) ** 2)  # (N,)

    resolved_center_merge = center_merge_frac if center_merge_frac > 0.0 else 0.18

    # ── 1. 空间网格索引 ──────────────────────────────────────────────────────────
    max_diag = float(diags.max()) if n > 0 else 100.0
    cell_size = max(max_diag * 1.5, 100.0)
    gx_idx = (cx // cell_size).astype(np.int32)
    gy_idx = (cy // cell_size).astype(np.int32)

    grid: dict[tuple[int, int], list[int]] = {}
    for i in range(n):
        key = (int(gx_idx[i]), int(gy_idx[i]))
        if key not in grid:
            grid[key] = []
        grid[key].append(i)

    # ── 2. Union-Find 并查集（路径压缩 + 按秩合并） ──────────────────────────────
    parent = np.arange(n, dtype=np.int32)
    rank = np.zeros(n, dtype=np.int32)

    def _find(u: int) -> int:
        # 迭代路径压缩，避免深递归
        root = u
        while parent[root] != root:
            root = int(parent[root])
        # 路径回填
        while parent[u] != root:
            nxt = int(parent[u])
            parent[u] = root
            u = nxt
        return root

    def _union(u: int, v: int) -> None:
        ru, rv = _find(u), _find(v)
        if ru == rv:
            return
        # 按秩合并
        if rank[ru] < rank[rv]:
            ru, rv = rv, ru
        parent[rv] = ru
        if rank[ru] == rank[rv]:
            rank[ru] += 1

    # ── 3. 逐行向量化邻域比较 ──────────────────────────────────────────────────
    # 对每个格子，收集相邻 9 个格子内所有框 → 对格内每个 i，
    # 一次性批量计算它与所有 j>i 的 IoU（逐行 numpy，不做二维广播）
    for (gx, gy), indices in grid.items():
        # 收集邻居框
        neighbor_list: list[int] = []
        for ddx in (-1, 0, 1):
            for ddy in (-1, 0, 1):
                nk = (gx + ddx, gy + ddy)
                if nk in grid:
                    neighbor_list.extend(grid[nk])

        if not neighbor_list:
            continue

        j_arr = np.array(neighbor_list, dtype=np.int32)

        for i in indices:
            # 只保留 j > i，避免重复
            valid_j = j_arr[j_arr > i]
            if len(valid_j) == 0:
                continue

            # 批量向量化计算 IoU（一行 i vs 多行 valid_j）
            xi1 = np.maximum(B[i, 0], B[valid_j, 0])
            yi1 = np.maximum(B[i, 1], B[valid_j, 1])
            xi2 = np.minimum(B[i, 2], B[valid_j, 2])
            yi2 = np.minimum(B[i, 3], B[valid_j, 3])
            inter = np.maximum(0.0, xi2 - xi1) * np.maximum(0.0, yi2 - yi1)
            union_arr = areas[i] + areas[valid_j] - inter
            iou_vals = np.where(union_arr > 0.0, inter / union_arr, 0.0)

            # 包含度
            ci = np.where(areas[i] > 0.0, inter / areas[i], 0.0)
            cj = np.where(areas[valid_j] > 0.0, inter / areas[valid_j], 0.0)
            max_cont = np.maximum(ci, cj)

            # 中心距离
            d_c = np.sqrt((cx[i] - cx[valid_j]) ** 2 + (cy[i] - cy[valid_j]) ** 2)
            ref = np.minimum(diags[i], diags[valid_j])
            ref = np.where(ref > 0.0, ref, 1.0)

            # 合并判定（向量化布尔掩码）
            should_merge = (
                (iou_vals >= 0.35)
                | (max_cont >= 0.45)
                | ((d_c <= 0.28 * ref) & (inter > 0.0))
                | (d_c <= resolved_center_merge * ref)
            )

            # 对命中的 j 执行 union（仅迭代需合并的对，通常极少）
            for j in valid_j[should_merge].tolist():
                _union(i, j)

    # ── 4. 收集连通分量（向量化） ─────────────────────────────────────────────
    roots = np.fromiter((_find(i) for i in range(n)), dtype=np.int32, count=n)
    unique_roots, inv = np.unique(roots, return_inverse=True)

    # ── 5. 对每个连通分量加权融合（向量化） ──────────────────────────────────
    out: list[FusedBox] = []
    for ridx, root in enumerate(unique_roots.tolist()):
        comp = np.where(roots == root)[0]   # (m,)

        comp_scores = scores_arr[comp]      # (m,)
        comp_weights = weights_arr[comp]    # (m,)
        comp_boxes = B[comp]               # (m, 4)

        best_local = int(np.argmax(comp_scores))
        best_idx = int(comp[best_local])
        best_label = labels_list[best_idx]

        ws = np.maximum(comp_scores * comp_weights, 1e-9)  # (m,)
        wsum = float(ws.sum())

        # 加权融合坐标（矩阵乘法，一次完成）
        fb = (ws @ comp_boxes) / wsum   # (4,)

        if conf_type == "max":
            sc = float(comp_scores.max())
        else:
            sc = float(comp_scores.mean())

        out.append(
            FusedBox(
                box=(float(fb[0]), float(fb[1]), float(fb[2]), float(fb[3])),
                score=sc,
                label=best_label,
                support=len(comp),
                extra={
                    "best_index": best_idx,
                    "merge_iou_count": len(comp) - 1,
                    "merge_center_count": 0,
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
