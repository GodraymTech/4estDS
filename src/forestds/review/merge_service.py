"""复核候选合并策略；阶段 C 提供人工工作集基础实现。"""
from __future__ import annotations

from typing import Any, Iterable


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


DUPLICATE_IOU = 0.7


class ReviewMergeService:
    """AI 候选写入工作集的策略。

    - ``append``: 冻结现有工作集, 仅并入与存量框不重复(IoU < DUPLICATE_IOU)的新候选;
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

        # 冻结框不可被替换, 因此重复候选只做丢弃, 只取存量之外的差集。
        for candidate in candidates:
            item = {**dict(candidate), "frozen": False}
            box = item.get("box_px")
            species = str(item.get("species") or "")
            spatial = indexes.setdefault(species, _SpatialIndex())
            if any(
                _iou(current[index].get("box_px"), box) >= DUPLICATE_IOU
                for index in spatial.query(box)
            ):
                continue
            current.append(item)
            spatial.insert(len(current) - 1, box)
        return mark_conflicts(current)


def non_max_suppression(items: Iterable[dict[str, Any]], threshold: float = 0.6) -> list[dict[str, Any]]:
    ordered = sorted((dict(item) for item in items), key=lambda item: float(item.get("confidence") or 0), reverse=True)
    kept: list[dict[str, Any]] = []
    indexes: dict[str, _SpatialIndex] = {}
    for item in ordered:
        species = str(item.get("species") or "")
        spatial = indexes.setdefault(species, _SpatialIndex())
        if any(_iou(item.get("box_px"), kept[index].get("box_px")) >= threshold for index in spatial.query(item.get("box_px"))):
            continue
        kept.append(item)
        spatial.insert(len(kept) - 1, item.get("box_px"))
    return mark_conflicts(kept)


def weighted_box_fusion(items: Iterable[dict[str, Any]], threshold: float = 0.6) -> list[dict[str, Any]]:
    """按类别融合重叠候选；跨类别重叠保留并标记冲突。"""
    pending = sorted((dict(item) for item in items), key=lambda item: float(item.get("confidence") or 0), reverse=True)
    spatial: dict[str, _SpatialIndex] = {}
    for index, item in enumerate(pending):
        species = str(item.get("species") or "")
        spatial.setdefault(species, _SpatialIndex()).insert(index, item.get("box_px"))
    remaining = set(range(len(pending)))
    fused: list[dict[str, Any]] = []
    for seed_index, seed in enumerate(pending):
        if seed_index not in remaining:
            continue
        remaining.remove(seed_index)
        species = str(seed.get("species") or "")
        group_indexes = [
            index
            for index in sorted(spatial[species].query(seed.get("box_px")))
            if index in remaining and _iou(pending[index].get("box_px"), seed.get("box_px")) >= threshold
        ]
        remaining.difference_update(group_indexes)
        group = [seed] + [pending[index] for index in group_indexes]
        if len(group) > 1:
            weights = [max(1e-6, float(item.get("confidence") or 0)) for item in group]
            total = sum(weights)
            seed["box_px"] = [
                sum(float(item["box_px"][axis]) * weight for item, weight in zip(group, weights)) / total
                for axis in range(4)
            ]
            seed["confidence"] = max(weights)
            seed["merged_ids"] = [item.get("id") for item in group]
        fused.append(seed)
    return mark_conflicts(fused)


def mark_conflicts(items: Iterable[dict[str, Any]], threshold: float = 0.5) -> list[dict[str, Any]]:
    values = [{**item, "conflict": False} for item in items]
    spatial = _SpatialIndex()
    for index, left in enumerate(values):
        for other_index in spatial.query(left.get("box_px")):
            right = values[other_index]
            if left.get("species") != right.get("species") and _iou(left.get("box_px"), right.get("box_px")) >= threshold:
                left["conflict"] = True
                right["conflict"] = True
        spatial.insert(index, left.get("box_px"))
    return values


def _center_in_scope(box: Any, scope: tuple[float, float, float, float]) -> bool:
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return False
    cx, cy = (float(box[0]) + float(box[2])) / 2, (float(box[1]) + float(box[3])) / 2
    return scope[0] <= cx <= scope[2] and scope[1] <= cy <= scope[3]


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
