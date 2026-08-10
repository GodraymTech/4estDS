"""复核模型适配器的稳定边界。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence


@dataclass
class PromptContext:
    mode: str
    class_ids: list[str]
    model_prompts: list[str] = field(default_factory=list)
    embedding: Any = None
    reference_image: Any = None
    reference_boxes: list[list[float]] = field(default_factory=list)
    reference_classes: list[int] = field(default_factory=list)
    encoded: bool = False


@dataclass(frozen=True)
class RasterWindow:
    x: int
    y: int
    width: int
    height: int
    pixels: Any


@dataclass
class ReviewPrediction:
    box_px: list[float]
    score: float
    category_id: str


class ReviewModelAdapter(Protocol):
    def capabilities(self) -> dict[str, Any]: ...
    def load(self) -> None: ...
    def prepare_text_prompts(self, prompts: Sequence[dict[str, Any]]) -> PromptContext: ...
    def prepare_visual_prompts(self, reference_image: Any, bboxes: Any, classes: Any, category_ids: Sequence[str] | None = None) -> PromptContext: ...
    def predict_batch(self, windows: Sequence[RasterWindow], prompt_context: PromptContext) -> Sequence[ReviewPrediction]: ...
    def normalize(self, results: Any, windows: Sequence[RasterWindow], prompt_context: PromptContext) -> Sequence[ReviewPrediction]: ...
