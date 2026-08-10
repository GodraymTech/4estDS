"""Ultralytics YOLOE 文本/视觉 Prompt 适配器。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np

from ..domain import ReviewValidationError
from .base import PromptContext, RasterWindow, ReviewPrediction


def _clean_rgb(img: Any) -> Any:
    """确保送入 Ultralytics / YOLOE / PyTorch 的图像恒为标准 (H, W, 3) uint8 连续 RGB。"""
    import numpy as np
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
        ref_clean = _clean_rgb(reference_image)

        embedding = None
        try:
            from ultralytics.models.yolo.yoloe import YOLOEVPDetectPredictor, YOLOEVPSegPredictor
            is_seg = "seg" in str(self.weights).lower() or getattr(self.model, "task", "") == "segment"
            predictor_cls = YOLOEVPSegPredictor if is_seg else YOLOEVPDetectPredictor
            predictor = predictor_cls(overrides={
                "model": str(self.weights),
                "conf": self.conf,
                "device": self.device,
                "imgsz": self.imgsz,
            })
            backend = getattr(self.model, "model", self.model)
            predictor.setup_model(backend, verbose=False)
            predictor.set_prompts({
                "bboxes": boxes.tolist(),
                "cls": [int(x) for x in labels.tolist()],
            })
            embedding = predictor.get_vpe(ref_clean)
            if embedding is not None and hasattr(self.model, "set_classes"):
                self.model.set_classes(class_ids, embedding)
        except Exception:
            # 兼容 FakeModel 或轻量 mock 环境
            pass

        return PromptContext(
            mode="visual",
            class_ids=class_ids,
            reference_image=ref_clean,
            reference_boxes=boxes.tolist(),
            reference_classes=[int(x) for x in labels.tolist()],
            embedding=embedding,
            encoded=True if embedding is not None else False,
        )

    def predict_batch(self, windows: Sequence[RasterWindow], prompt_context: PromptContext) -> list[ReviewPrediction]:
        if not windows:
            return []
        self.load()
        sources = [_clean_rgb(window.pixels) for window in windows]
        kwargs = {"conf": self.conf, "imgsz": self.imgsz, "device": self.device, "verbose": False}
        if prompt_context.mode == "visual" and not prompt_context.encoded:
            from ultralytics.models.yolo.yoloe import YOLOEVPDetectPredictor, YOLOEVPSegPredictor
            is_seg = "seg" in str(self.weights).lower() or getattr(self.model, "task", "") == "segment"
            predictor_cls = YOLOEVPSegPredictor if is_seg else YOLOEVPDetectPredictor
            results = self.model.predict(
                sources,
                visual_prompts={
                    "bboxes": prompt_context.reference_boxes,
                    "cls": [int(x) for x in prompt_context.reference_classes],
                },
                refer_image=_clean_rgb(prompt_context.reference_image),
                predictor=predictor_cls,
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
