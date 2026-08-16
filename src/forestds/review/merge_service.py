"""复核候选合并策略；复用 postprocess/wbf 生产级多维融合引擎。"""
from __future__ import annotations

import math
import uuid
from typing import Any, Iterable

from ..postprocess.wbf import fuse


class _SpatialIndex:
    """小型像素框网格索引；避免万级候选合并退化为 O(n²)。"""

    def __init__(self, cell_size: float = 64.0):
        self.cell_size = cell_size
        self.buckets: dict[tuple[int, int], set[int]] = {}
        self.oversized: set[int] = set()
        self.all_indices: set[int] = set()

    def _cells(self, value: Any) -> list[tuple[int, int]] | None:
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            return None
        try:
            x1, y1, x2, y2 = map(float, value)
        except (TypeError, ValueError):
            return None
        if x2 <= x1 or y2 <= y1:
            return None
        left, top = int(x1 // self.cell_size), int(y1 // self.cell_size)
        right, bottom = int(x2 // self.cell_size), int(y2 // self.cell_size)
        if (right - left + 1) * (bottom - top + 1) > 4096:
            return []
        return [(x, y) for x in range(left, right + 1) for y in range(top, bottom + 1)]

    def insert(self, index: int, box: Any) -> None:
        cells = self._cells(box)
        if cells is None:
            return
        self.all_indices.add(index)
        if not cells:
            self.oversized.add(index)
            return
        for cell in cells:
            self.buckets.setdefault(cell, set()).add(index)

    def query(self, box: Any) -> set[int]:
        cells = self._cells(box)
        if cells is None:
            return set()
        if not cells:
            return set(self.all_indices)
        result = set(self.oversized)
        for cell in cells:
            result.update(self.buckets.get(cell, ()))
        return result


def _is_overlap(box_a: Any, box_b: Any, iou_thr: float = 0.35, cont_thr: float = 0.45) -> bool:
    """复合重叠判定：结合标准 IoU、包含度 (IoS) 与相交中心距。"""
    if not isinstance(box_a, (list, tuple)) or not isinstance(box_b, (list, tuple)) or len(box_a) != 4 or len(box_b) != 4:
        return False
    try:
        ax1, ay1, ax2, ay2 = map(float, box_a)
        bx1, by1, bx2, by2 = map(float, box_b)
    except (TypeError, ValueError):
        return False
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0.0:
        return False
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    iou_val = inter / union if union > 0 else 0.0
    if iou_val >= iou_thr:
        return True
    cont_val = max(inter / area_a if area_a > 0 else 0.0, inter / area_b if area_b > 0 else 0.0)
    if cont_val >= cont_thr:
        return True
    cax, cay = (ax1 + ax2) / 2, (ay1 + ay2) / 2
    cbx, cby = (bx1 + bx2) / 2, (by1 + by2) / 2
    dist_c = math.hypot(cax - cbx, cay - cby)
    diag_min = min(math.hypot(ax2 - ax1, ay2 - ay1), math.hypot(bx2 - bx1, by2 - by1))
    if diag_min > 0 and dist_c <= 0.28 * diag_min:
        return True
    return False


class ReviewMergeService:
    """AI 候选写入工作集的策略。

    - ``append``: 冻结现有工作集, 仅并入与存量框不重复(复合重叠判定)的新候选;
      冻结框不可删除, 几何与树种锁定, 只保留人工判定与备注两个自由度。
    - ``replace_all``: 整体丢弃旧工作集, 以本次候选为唯一真相。
    """

    def append(
        self,
        existing: Iterable[dict[str, Any]],
        incoming: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """按 id 覆盖式并入; 存量项统一冻结, 新并入项保持可编辑。"""
        by_id: dict[str, dict[str, Any]] = {
            str(item.get("id")): {**dict(item), "frozen": True} for item in existing
        }
        for item in incoming:
            by_id[str(item.get("id"))] = {**dict(item), "frozen": False}
        return list(by_id.values())

    def apply(
        self,
        mode: str,
        existing: Iterable[dict[str, Any]],
        candidates: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if mode == "replace_all":
            return mark_conflicts({**dict(item), "frozen": False} for item in candidates)
        if mode != "append":
            raise ValueError(f"unknown merge mode: {mode}")

        current = [{**dict(item), "frozen": True} for item in existing]
        indexes: dict[str, _SpatialIndex] = {}
        for index, item in enumerate(current):
            species = str(item.get("species") or "")
            indexes.setdefault(species, _SpatialIndex()).insert(index, item.get("box_px"))

        # 冻结框不可被替换, 仅保留与同品类存量不重复的新候选
        for candidate in candidates:
            item = {**dict(candidate), "frozen": False}
            box = item.get("box_px")
            species = str(item.get("species") or "")
            spatial = indexes.setdefault(species, _SpatialIndex())
            if any(
                _is_overlap(current[index].get("box_px"), box)
                for index in spatial.query(box)
            ):
                continue
            current.append(item)
            spatial.insert(len(current) - 1, box)
        return mark_conflicts(current)


def non_max_suppression(items: Iterable[dict[str, Any]], threshold: float = 0.45) -> list[dict[str, Any]]:
    ordered = sorted((dict(item) for item in items), key=lambda item: float(item.get("confidence") or 0), reverse=True)
    kept: list[dict[str, Any]] = []
    indexes: dict[str, _SpatialIndex] = {}
    for item in ordered:
        species = str(item.get("species") or "")
        spatial = indexes.setdefault(species, _SpatialIndex())
        if any(_is_overlap(item.get("box_px"), kept[index].get("box_px"), iou_thr=threshold) for index in spatial.query(item.get("box_px"))):
            continue
        kept.append(item)
        spatial.insert(len(kept) - 1, item.get("box_px"))
    return mark_conflicts(kept)


def weighted_box_fusion(
    items: Iterable[dict[str, Any]],
    threshold: float = 0.45,
    *,
    conf_type: str = "max",
    center_merge_frac: float = 0.18,
) -> list[dict[str, Any]]:
    """按类别使用尺度感知加权框融合 (WBF) 消除重叠候选；跨类别重叠保留并标记冲突。"""
    raw_list = list(items)
    if not raw_list:
        return []

    # 按类别分桶执行向量化 WBF
    by_species: dict[str, list[dict[str, Any]]] = {}
    for item in raw_list:
        species = str(item.get("species") or "tree")
        by_species.setdefault(species, []).append(item)

    fused_candidates: list[dict[str, Any]] = []
    for species, species_items in by_species.items():
        boxes = [tuple(map(float, it["box_px"])) for it in species_items if isinstance(it.get("box_px"), (list, tuple)) and len(it["box_px"]) == 4]
        if not boxes:
            continue
        valid_items = [it for it in species_items if isinstance(it.get("box_px"), (list, tuple)) and len(it["box_px"]) == 4]
        scores = [float(it.get("confidence") or 0.0) for it in valid_items]
        labels = [str(it.get("species") or species) for it in valid_items]

        fused_boxes = fuse(
            boxes,
            scores,
            labels=labels,
            iou_thr=threshold,
            conf_type=conf_type,
            center_merge_frac=center_merge_frac,
        )

        for fb in fused_boxes:
            fused_candidates.append({
                "id": f"ai_{uuid.uuid4().hex[:12]}",
                "species": fb.label,
                "confidence": round(float(fb.score), 4),
                "box_px": [round(float(c), 2) for c in fb.box],
                "source": "ai",
                "confirmed": False,
                "status": "pending",
                "conflict": False,
                "frozen": False,
            })

    return mark_conflicts(fused_candidates)


def mark_conflicts(items: Iterable[dict[str, Any]], threshold: float = 0.35) -> list[dict[str, Any]]:
    values = [{**item, "conflict": False} for item in items]
    spatial = _SpatialIndex()
    for index, left in enumerate(values):
        for other_index in spatial.query(left.get("box_px")):
            right = values[other_index]
            if left.get("species") != right.get("species") and _is_overlap(left.get("box_px"), right.get("box_px"), iou_thr=threshold, cont_thr=0.45):
                left["conflict"] = True
                right["conflict"] = True
        spatial.insert(index, left.get("box_px"))
    return values


def _iou(left: Any, right: Any) -> float:
    if not isinstance(left, (list, tuple)) or not isinstance(right, (list, tuple)) or len(left) != 4 or len(right) != 4:
        return 0.0
    lx1, ly1, lx2, ly2 = map(float, left)
    rx1, ry1, rx2, ry2 = map(float, right)
    width = max(0.0, min(lx2, rx2) - max(lx1, rx1))
    height = max(0.0, min(ly2, ry2) - max(ly1, ry1))
    intersection = width * height
    union = max(0.0, (lx2 - lx1) * (ly2 - ly1)) + max(0.0, (rx2 - rx1) * (ry2 - ry1)) - intersection
    return intersection / union if union > 0 else 0.0


def _calculate_union_area(boxes: list[tuple[float, float, float, float]]) -> float:
    """计算一组 2D 轴对齐矩形的多边形并集总面积（基于 X 轴区间扫描线算法）。"""
    if not boxes:
        return 0.0
    if len(boxes) == 1:
        b = boxes[0]
        return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])

    # 提取所有不重复的 X 切片事件点
    x_events = sorted(set([b[0] for b in boxes] + [b[2] for b in boxes]))
    total_area = 0.0

    for i in range(len(x_events) - 1):
        x_left = x_events[i]
        x_right = x_events[i + 1]
        width = x_right - x_left
        if width <= 0.0:
            continue

        # 找出跨越 [x_left, x_right] 切片的所有 Y 区间
        y_intervals = [
            (b[1], b[3])
            for b in boxes
            if b[0] <= x_left and b[2] >= x_right
        ]
        if not y_intervals:
            continue

        # 合并重叠的一维 Y 区间
        y_intervals.sort(key=lambda item: item[0])
        merged_y_len = 0.0
        cur_y1, cur_y2 = y_intervals[0]
        for ny1, ny2 in y_intervals[1:]:
            if ny1 < cur_y2:
                cur_y2 = max(cur_y2, ny2)
            else:
                merged_y_len += max(0.0, cur_y2 - cur_y1)
                cur_y1, cur_y2 = ny1, ny2
        merged_y_len += max(0.0, cur_y2 - cur_y1)

        total_area += width * merged_y_len

    return total_area


def filter_candidates_by_existing(
    candidates: Iterable[dict[str, Any]],
    existing_items: Iterable[dict[str, Any]],
    max_coverage_ratio: float = 0.50,
) -> list[dict[str, Any]]:
    """剔除被工作集存量标注覆盖面积 >= max_coverage_ratio (默认50%) 的候选框。

    - Level 1 (单框快判): 若任意单个已有框与候选框相交面积 >= 50% 自身面积，立即剔除;
    - Level 2 (上限剪枝): 若所有相交面积之和 < 50%，必定不满足，立即保留;
    - Level 3 (联合精算): 仅当多框累积可能超过 50% 时，计算局部精确多边形并集面积。
    """
    existing_list = [
        item for item in existing_items
        if isinstance(item.get("box_px"), (list, tuple)) and len(item["box_px"]) == 4
    ]
    if not existing_list:
        return list(candidates)

    spatial = _SpatialIndex(cell_size=64.0)
    for idx, item in enumerate(existing_list):
        spatial.insert(idx, item.get("box_px"))

    kept: list[dict[str, Any]] = []
    for cand in candidates:
        box = cand.get("box_px")
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        cx1, cy1, cx2, cy2 = map(float, box)
        cand_area = max(0.0, cx2 - cx1) * max(0.0, cy2 - cy1)
        if cand_area <= 0.0:
            continue

        neighbor_indices = spatial.query(box)
        if not neighbor_indices:
            kept.append(cand)
            continue

        intersections: list[tuple[float, float, float, float]] = []
        max_single_inter = 0.0
        for n_idx in neighbor_indices:
            ex_box = existing_list[n_idx].get("box_px")
            ex1, ey1, ex2, ey2 = map(float, ex_box)
            ix1, iy1 = max(cx1, ex1), max(cy1, ey1)
            ix2, iy2 = min(cx2, ex2), min(cy2, ey2)
            iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
            inter_area = iw * ih
            if inter_area > 0.0:
                intersections.append((ix1, iy1, ix2, iy2))
                if inter_area > max_single_inter:
                    max_single_inter = inter_area

        if not intersections:
            kept.append(cand)
            continue

        # Level 1: 单框覆盖 >= 50%
        if max_single_inter >= max_coverage_ratio * cand_area:
            continue

        # Level 2: 上限剪枝
        sum_inter = sum((b[2] - b[0]) * (b[3] - b[1]) for b in intersections)
        if sum_inter < max_coverage_ratio * cand_area:
            kept.append(cand)
            continue

        # Level 3: 多框联合精确覆盖面积
        union_area = _calculate_union_area(intersections)
        if union_area >= max_coverage_ratio * cand_area:
            continue

        kept.append(cand)

    return kept
