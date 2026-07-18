"""复核候选合并策略；阶段 C 提供人工工作集基础实现。"""
from __future__ import annotations

from typing import Any, Iterable


class ReviewMergeService:
    def append(self, existing: Iterable[dict[str, Any]], incoming: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        by_id = {str(item.get("id")): dict(item) for item in existing}
        for item in incoming:
            by_id[str(item.get("id"))] = dict(item)
        return list(by_id.values())

    def apply(
        self,
        mode: str,
        existing: Iterable[dict[str, Any]],
        candidates: Iterable[dict[str, Any]],
        scope: tuple[float, float, float, float] | None,
    ) -> list[dict[str, Any]]:
        current = [dict(item) for item in existing]
        if mode == "replace_ai_in_scope":
            current = [
                item for item in current
                if not (
                    item.get("source") == "ai"
                    and not item.get("confirmed")
                    and (scope is None or _center_in_scope(item.get("box_px"), scope))
                )
            ]
        elif mode != "append":
            raise ValueError(f"unknown merge mode: {mode}")
        for candidate in candidates:
            item = dict(candidate)
            duplicate = next((old for old in current if old.get("species") == item.get("species") and _iou(old.get("box_px"), item.get("box_px")) >= 0.7), None)
            if duplicate is None:
                current.append(item)
            elif float(item.get("confidence") or 0) > float(duplicate.get("confidence") or 0) and duplicate.get("source") == "ai" and not duplicate.get("confirmed"):
                current[current.index(duplicate)] = item
        return mark_conflicts(current)


def non_max_suppression(items: Iterable[dict[str, Any]], threshold: float = 0.6) -> list[dict[str, Any]]:
    ordered = sorted((dict(item) for item in items), key=lambda item: float(item.get("confidence") or 0), reverse=True)
    kept: list[dict[str, Any]] = []
    for item in ordered:
        if any(item.get("species") == old.get("species") and _iou(item.get("box_px"), old.get("box_px")) >= threshold for old in kept):
            continue
        kept.append(item)
    return mark_conflicts(kept)


def weighted_box_fusion(items: Iterable[dict[str, Any]], threshold: float = 0.6) -> list[dict[str, Any]]:
    """按类别融合重叠候选；跨类别重叠保留并标记冲突。"""
    pending = sorted((dict(item) for item in items), key=lambda item: float(item.get("confidence") or 0), reverse=True)
    fused: list[dict[str, Any]] = []
    while pending:
        seed = pending.pop(0)
        group = [seed]
        rest: list[dict[str, Any]] = []
        for item in pending:
            if item.get("species") == seed.get("species") and _iou(item.get("box_px"), seed.get("box_px")) >= threshold:
                group.append(item)
            else:
                rest.append(item)
        pending = rest
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
    for index, left in enumerate(values):
        for right in values[index + 1:]:
            if left.get("species") != right.get("species") and _iou(left.get("box_px"), right.get("box_px")) >= threshold:
                left["conflict"] = True
                right["conflict"] = True
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
