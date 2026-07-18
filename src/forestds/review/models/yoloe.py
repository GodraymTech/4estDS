"""Ultralytics YOLOE 文本/视觉 Prompt 适配器。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np

from ..domain import ReviewValidationError
from .base import PromptContext, RasterWindow, ReviewPrediction


class YOLOEReviewAdapter:
    def __init__(
        self,
        weights: str | Path,
        *,
        mobileclip: str | Path | None = None,
        device: str | None = None,
        conf: float = 0.25,
        imgsz: int = 1024,
        model_factory: Callable[[str], Any] | None = None,
    ):
        self.weights = _resolve_model_path(weights)
        self.mobileclip = _resolve_model_path(mobileclip) if mobileclip else None
        self.device = device
        self.conf = float(conf)
        self.imgsz = int(imgsz)
        self.model_factory = model_factory
        self.model: Any = None
        self._text_cache: dict[tuple[str, ...], Any] = {}

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": "yoloe",
            "text_prompt": True,
            "visual_prompt": True,
            "segmentation": "seg" in self.weights.name,
            "weights": str(self.weights),
            "mobileclip": str(self.mobileclip) if self.mobileclip else None,
            "available": self.weights.is_file() and (self.mobileclip is None or self.mobileclip.is_file()),
        }

    def load(self) -> None:
        if self.model is not None:
            return
        missing = [str(path) for path in (self.weights, self.mobileclip) if path is not None and not path.is_file()]
        if missing:
            raise ReviewValidationError(
                "YOLOE 模型文件不存在，请检查 review.models 配置。",
                code="review_model_missing",
                details={"paths": missing},
            )
        factory = self.model_factory
        if factory is None:
            from ultralytics import YOLOE

            factory = lambda path: YOLOE(path, verbose=False)
        self.model = factory(str(self.weights))
        backend = getattr(self.model, "model", None)
        if self.mobileclip is not None and backend is not None and hasattr(backend, "parameters"):
            from ultralytics.nn.text_model import MobileCLIPTS

            device = next(backend.parameters()).device
            backend.clip_model = MobileCLIPTS(device, weight=str(self.mobileclip))

    def prepare_text_prompts(self, prompts: Sequence[dict[str, Any]]) -> PromptContext:
        self.load()
        if not prompts:
            raise ReviewValidationError("至少需要一个文本 Prompt。", code="text_prompt_required")
        class_ids = [str(item.get("category_id") or item.get("display_name") or "").strip() for item in prompts]
        model_prompts = [str(item.get("model_prompt") or item.get("display_name") or "").strip() for item in prompts]
        if any(not value for value in class_ids + model_prompts):
            raise ReviewValidationError("文本 Prompt 的类别与模型描述不能为空。", code="invalid_text_prompt")
        key = tuple(model_prompts)
        embedding = self._text_cache.get(key)
        if embedding is None:
            backend = getattr(self.model, "model", None)
            if self.mobileclip is not None and backend is not None and hasattr(backend, "get_text_pe"):
                embedding = backend.get_text_pe(model_prompts, cache_clip_model=True)
            else:
                embedding = self.model.get_text_pe(model_prompts)
            self._text_cache[key] = embedding
        self.model.set_classes(model_prompts, embedding)
        return PromptContext(mode="text", class_ids=class_ids, model_prompts=model_prompts, embedding=embedding, encoded=True)

    def prepare_visual_prompts(
        self,
        reference_image: Any,
        bboxes: Any,
        classes: Any,
        category_ids: Sequence[str] | None = None,
    ) -> PromptContext:
        self.load()
        boxes = np.asarray(bboxes, dtype=float).reshape(-1, 4)
        labels = np.asarray(classes, dtype=int).reshape(-1)
        if len(boxes) == 0 or len(boxes) != len(labels):
            raise ReviewValidationError("视觉 Prompt 需要等量的参考框和 class ID。", code="invalid_visual_prompt")
        class_ids = list(category_ids or [str(value) for value in sorted(set(labels.tolist()))])
        return PromptContext(
            mode="visual",
            class_ids=class_ids,
            reference_image=reference_image,
            reference_boxes=boxes.tolist(),
            reference_classes=labels.tolist(),
        )

    def predict_batch(self, windows: Sequence[RasterWindow], prompt_context: PromptContext) -> list[ReviewPrediction]:
        if not windows:
            return []
        self.load()
        sources = [window.pixels for window in windows]
        kwargs = {"conf": self.conf, "imgsz": self.imgsz, "device": self.device, "verbose": False}
        if prompt_context.mode == "visual" and not prompt_context.encoded:
            results = self.model.predict(
                sources,
                visual_prompts={"bboxes": prompt_context.reference_boxes, "cls": prompt_context.reference_classes},
                refer_image=prompt_context.reference_image,
                **kwargs,
            )
            prompt_context.encoded = True
        else:
            results = self.model.predict(sources, **kwargs)
        return list(self.normalize(results, windows, prompt_context))

    def normalize(
        self,
        results: Any,
        windows: Sequence[RasterWindow],
        prompt_context: PromptContext,
    ) -> list[ReviewPrediction]:
        normalized: list[ReviewPrediction] = []
        for result, window in zip(results or [], windows):
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            xyxy = _to_numpy(getattr(boxes, "xyxy", []))
            scores = _to_numpy(getattr(boxes, "conf", []))
            classes = _to_numpy(getattr(boxes, "cls", [])).astype(int)
            masks = getattr(getattr(result, "masks", None), "data", None)
            mask_values = _to_numpy(masks) if masks is not None else None
            for index, local_box in enumerate(xyxy):
                class_index = int(classes[index]) if index < len(classes) else 0
                category = prompt_context.class_ids[min(class_index, len(prompt_context.class_ids) - 1)]
                normalized.append(ReviewPrediction(
                    box_px=[
                        float(local_box[0]) + window.x,
                        float(local_box[1]) + window.y,
                        float(local_box[2]) + window.x,
                        float(local_box[3]) + window.y,
                    ],
                    score=float(scores[index]) if index < len(scores) else 0.0,
                    category_id=category,
                    mask=mask_values[index] if mask_values is not None and index < len(mask_values) else None,
                    source_window=(window.x, window.y, window.width, window.height),
                ))
        return normalized


def _to_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        return value.numpy()
    return np.asarray(value)


def _resolve_model_path(value: str | Path) -> Path:
    raw = Path(value).expanduser()
    if raw.is_absolute():
        return raw
    candidates = [Path.cwd() / raw]
    candidates.extend(parent / raw for parent in Path.cwd().parents)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()
