"""无 GPU 的确定性复核模型，用于开发与事务测试。"""
from __future__ import annotations

from typing import Any, Sequence

from .base import PromptContext, RasterWindow, ReviewPrediction


class MockReviewAdapter:
    def capabilities(self) -> dict[str, Any]:
        return {"name": "mock_review", "text_prompt": True, "visual_prompt": True, "segmentation": True}

    def load(self) -> None:
        return None

    def prepare_text_prompts(self, prompts: Sequence[dict[str, Any]]) -> PromptContext:
        return PromptContext(
            mode="text",
            class_ids=[str(item.get("category_id") or item.get("display_name") or "object") for item in prompts],
            model_prompts=[str(item.get("model_prompt") or item.get("display_name") or "object") for item in prompts],
        )

    def prepare_visual_prompts(self, reference_image: Any, bboxes: Any, classes: Any, category_ids=None) -> PromptContext:
        return PromptContext(
            mode="visual",
            class_ids=list(category_ids or [str(value) for value in sorted(set(classes))]),
            reference_image=reference_image,
            reference_boxes=[list(map(float, value)) for value in bboxes],
            reference_classes=[int(value) for value in classes],
        )

    def predict_batch(self, windows: Sequence[RasterWindow], prompt_context: PromptContext) -> list[ReviewPrediction]:
        return []

    def normalize(self, results, windows, prompt_context):
        return list(results or [])
