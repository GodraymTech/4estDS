from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from forestds.review.models import RasterWindow
from forestds.review.models.yoloe import YOLOEReviewAdapter


class FakeModel:
    def __init__(self):
        self.text_calls = 0
        self.set_calls = []
        self.predict_calls = []

    def get_text_pe(self, prompts):
        self.text_calls += 1
        return {"prompts": tuple(prompts)}

    def set_classes(self, prompts, embedding):
        self.set_calls.append((tuple(prompts), embedding))

    def predict(self, sources, **kwargs):
        self.predict_calls.append(kwargs)
        return [SimpleNamespace(
            boxes=SimpleNamespace(
                xyxy=np.array([[1, 2, 5, 8]], dtype=float),
                conf=np.array([0.9]),
                cls=np.array([0]),
            ),
            masks=None,
        ) for _ in sources]


def test_text_prompt_maps_display_and_model_prompt_with_embedding_cache(tmp_path) -> None:
    weights = tmp_path / "yoloe.pt"
    weights.touch()
    backend = FakeModel()
    adapter = YOLOEReviewAdapter(weights, model_factory=lambda _: backend)
    prompts = [{"category_id": "红树", "display_name": "红树", "model_prompt": "mangrove tree crown"}]

    first = adapter.prepare_text_prompts(prompts)
    second = adapter.prepare_text_prompts(prompts)

    assert first.class_ids == ["红树"]
    assert first.model_prompts == ["mangrove tree crown"]
    assert first.embedding is second.embedding
    assert backend.text_calls == 1


def test_visual_prompt_encodes_reference_once_without_projecting_boxes(tmp_path) -> None:
    weights = tmp_path / "yoloe-seg.pt"
    weights.touch()
    backend = FakeModel()
    adapter = YOLOEReviewAdapter(weights, model_factory=lambda _: backend)
    reference = np.zeros((32, 32, 3), dtype=np.uint8)
    context = adapter.prepare_visual_prompts(reference, [[2, 3, 10, 12]], [0], ["秋茄"])
    windows = [RasterWindow(100, 200, 32, 32, np.zeros((32, 32, 3), dtype=np.uint8))]

    first = adapter.predict_batch(windows, context)
    second = adapter.predict_batch(windows, context)

    assert context.reference_boxes == [[2.0, 3.0, 10.0, 12.0]]
    assert first[0].box_px == [101.0, 202.0, 105.0, 208.0]
    assert second[0].category_id == "秋茄"
    assert "visual_prompts" in backend.predict_calls[0]
    assert "visual_prompts" not in backend.predict_calls[1]


def test_real_visual_prompt_multi_window_inference() -> None:
    from pathlib import Path
    weights = Path(".4estDS/models/multimodal/yoloe-26x-seg.pt")
    if not weights.is_file():
        return
    adapter = YOLOEReviewAdapter(weights, conf=0.01, device="cpu")
    ref = np.zeros((512, 512, 3), dtype=np.uint8)
    ref[200:250, 200:250] = 200
    context = adapter.prepare_visual_prompts(ref, [[200, 200, 250, 250]], [0], ["tree"])
    windows = [
        RasterWindow(0, 0, 512, 512, ref),
        RasterWindow(512, 0, 512, 512, ref),
    ]
    preds = adapter.predict_batch(windows, context)
    assert isinstance(preds, list)
