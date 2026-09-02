"""标准闭集 YOLO 遥感林木专家模型适配器 (如 M07 等)。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np

from ..domain import ReviewValidationError
from .base import PromptContext, RasterWindow, ReviewPrediction


def _clean_rgb(img: Any) -> Any:
    """确保输入图像恒为标准 (H, W, 3) uint8 连续 RGB。"""
    if not isinstance(img, np.ndarray):
        img = np.asarray(img)
    if img.ndim == 4:
        img = img[0]
    if img.ndim == 2:
        img = np.repeat(img[:, :, None], 3, axis=2)
    elif img.ndim == 3:
        if img.shape[0] in (1, 2, 3, 4, 5, 8) and img.shape[0] < min(img.shape[1], img.shape[2]):
            img = img.transpose(1, 2, 0)
        if img.shape[2] == 1:
            img = np.repeat(img, 3, axis=2)
        elif img.shape[2] >= 4:
            img = img[:, :, :3]
        elif img.shape[2] == 2:
            img = np.pad(img, ((0, 0), (0, 0), (0, 1)), mode="edge")

    if img.dtype != np.uint8:
        if np.issubdtype(img.dtype, np.floating):
            max_val = float(np.nanmax(img)) if img.size else 1.0
            if max_val <= 1.0:
                img = (np.clip(img, 0, 1) * 255.0).astype(np.uint8)
            else:
                img = np.clip(img, 0, 255).astype(np.uint8)
        elif img.dtype in (np.uint16, np.int16, np.uint32, np.int32):
            max_val = float(np.max(img)) if img.size else 255.0
            if max_val > 255.0:
                img = np.clip(img / (max_val / 255.0), 0, 255).astype(np.uint8)
            else:
                img = np.clip(img, 0, 255).astype(np.uint8)
        else:
            img = np.clip(img, 0, 255).astype(np.uint8)

    return np.ascontiguousarray(img)


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


class YOLOReviewAdapter:
    """闭集 YOLO 专家模型（如 M07 等）复核适配器：无需 Prompt，直接探测已训练好的林木类别。"""

    def __init__(
        self,
        weights: str | Path,
        *,
        device: str | None = None,
        conf: float = 0.25,
        imgsz: int = 640,
        model_factory: Callable[[str], Any] | None = None,
    ):
        self.weights = _resolve_model_path(weights)
        self.device = device
        self.conf = float(conf)
        self.imgsz = int(imgsz)
        self.model_factory = model_factory
        self.model: Any = None
        self.names: dict[int, str] = {}

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": "yolo",
            "text_prompt": False,
            "visual_prompt": False,
            "direct_detection": True,
            "segmentation": False,
            "weights": str(self.weights),
            "available": self.weights.is_file(),
            "classes": list(self.names.values()) if self.names else [],
        }

    def load(self) -> None:
        if self.model is not None:
            return
        if not self.weights.is_file():
            raise ReviewValidationError(
                f"YOLO 模型权重文件不存在：{self.weights}",
                code="review_model_missing",
                details={"path": str(self.weights)},
            )
        factory = self.model_factory
        if factory is None:
            from ultralytics import YOLO

            factory = lambda path: YOLO(path, verbose=False)
        self.model = factory(str(self.weights))
        self.names = getattr(self.model, "names", {}) or {}

    def prepare_text_prompts(self, prompts: Sequence[dict[str, Any]]) -> PromptContext:
        self.load()
        class_ids = [p["category_id"] for p in prompts if "category_id" in p] or list(self.names.values())
        return PromptContext(mode="direct", class_ids=class_ids)

    def prepare_visual_prompts(
        self,
        reference_image: Any,
        bboxes: Any,
        classes: Any,
        category_ids: Sequence[str] | None = None,
    ) -> PromptContext:
        self.load()
        class_ids = list(category_ids or self.names.values())
        return PromptContext(mode="direct", class_ids=class_ids)

    def predict_batch(self, windows: Sequence[RasterWindow], prompt_context: PromptContext) -> list[ReviewPrediction]:
        if not windows:
            return []
        self.load()
        sources = [_clean_rgb(window.pixels) for window in windows]
        kwargs = {"conf": self.conf, "imgsz": self.imgsz, "device": self.device, "verbose": False}
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
            for index, local_box in enumerate(xyxy):
                cls_idx = int(classes[index]) if index < len(classes) else 0
                model_cls_name = str(self.names.get(cls_idx, cls_idx))

                matched_cat = model_cls_name
                if prompt_context and prompt_context.class_ids:
                    for cid in prompt_context.class_ids:
                        if (
                            cid.lower() == model_cls_name.lower()
                            or model_cls_name.lower() in cid.lower()
                            or cid.lower() in model_cls_name.lower()
                        ):
                            matched_cat = cid
                            break
                    else:
                        matched_cat = prompt_context.class_ids[min(cls_idx, len(prompt_context.class_ids) - 1)]

                normalized.append(
                    ReviewPrediction(
                        box_px=[
                            float(local_box[0]) + window.x,
                            float(local_box[1]) + window.y,
                            float(local_box[2]) + window.x,
                            float(local_box[3]) + window.y,
                        ],
                        score=float(scores[index]) if index < len(scores) else 1.0,
                        category_id=matched_cat,
                    )
                )
        return normalized
