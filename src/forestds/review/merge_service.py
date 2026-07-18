"""复核候选合并策略；阶段 C 提供人工工作集基础实现。"""
from __future__ import annotations

from typing import Any, Iterable


class ReviewMergeService:
    def append(self, existing: Iterable[dict[str, Any]], incoming: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        by_id = {str(item.get("id")): dict(item) for item in existing}
        for item in incoming:
            by_id[str(item.get("id"))] = dict(item)
        return list(by_id.values())
