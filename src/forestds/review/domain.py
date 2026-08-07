"""单 TIFF 复核领域对象与错误。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

ReviewMode = Literal["inherit", "fresh"]
ReviewMergeMode = Literal["append", "replace_all"]

#: 冻结框仅允许人工改动的字段。
#: 冻结语义由 append 合并模式产生: 上一轮已并入工作集的存量框不可删除,
#: 几何(box_px/box_geo)与树种(species)锁定, 只保留判定与备注两个自由度。
FROZEN_EDITABLE_FIELDS: frozenset[str] = frozenset({"status", "note"})


class ReviewError(RuntimeError):
    def __init__(self, message: str, *, code: str, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    def as_detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": self.details}


class ReviewNotFound(ReviewError):
    pass


class ReviewConflict(ReviewError):
    pass


class ReviewValidationError(ReviewError):
    pass


@dataclass(frozen=True)
class ReviewSession:
    session_id: str
    phase_id: str
    tiff_id: str
    tract_phase_pk: str
    mode: ReviewMode
    base_run_id: str | None
    expected_active_run_id: str | None
    status: str
    revision: int
    draft_path: str
    published_run_id: str | None
    created_at: str
    updated_at: str


@dataclass
class ReviewWorkspace:
    revision: int = 0
    items: list[dict[str, Any]] = field(default_factory=list)
    category_catalog: list[dict[str, Any]] = field(default_factory=list)
    visible_categories: list[str] = field(default_factory=list)
    active_category: str | None = None
    text_prompts: list[dict[str, Any]] = field(default_factory=list)
    visual_exemplars: list[dict[str, Any]] = field(default_factory=list)
    attempts: list[dict[str, Any]] = field(default_factory=list)
    undo_stack: list[dict[str, Any]] = field(default_factory=list)
    redo_stack: list[dict[str, Any]] = field(default_factory=list)
    applied_operations: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReviewWorkspace":
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value[key] for key in allowed if key in value})


@dataclass(frozen=True)
class WorkspacePatch:
    session_id: str
    revision: int
    items: tuple[dict[str, Any], ...]
    summary: dict[str, int]
    changed_items: tuple[dict[str, Any], ...] = ()
    deleted_item_ids: tuple[str, ...] = ()
    replace_all: bool = False


def is_frozen(item: Mapping[str, Any]) -> bool:
    """是否为冻结框(不可删除、几何与树种锁定)。"""
    return bool(item.get("frozen"))


def workspace_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    active = [item for item in items if item.get("status") != "rejected"]
    return {
        "total": len(active),
        "accepted": sum(item.get("status") == "accepted" for item in items),
        "rejected": sum(item.get("status") == "rejected" for item in items),
        "conflicts": sum(bool(item.get("conflict")) for item in active),
        "frozen": sum(is_frozen(item) for item in active),
    }
