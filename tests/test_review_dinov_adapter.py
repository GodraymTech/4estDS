from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import torch

from forestds.review.models import RasterWindow
from forestds.review.models.dinov import DINOvReviewAdapter


class FakeDINOvBackend:
    def __init__(self):
        self.model = SimpleNamespace(
            get_encoder_feature=self._get_encoder_feature,
            get_visual_prompt_content_feature=self._get_visual_prompt_content_feature,
            evaluate_demo_content_openset_multi_with_content_features=self._evaluate,
        )

    def _get_encoder_feature(self, inputs):
        return torch.zeros(1), torch.zeros(1), 640, 640

    def _get_visual_prompt_content_feature(self, features, rand_shape, h, w):
        return torch.zeros(1), torch.zeros(1), torch.zeros(1)

    def _evaluate(self, inputs, mask_feat, ms_feat, query_label, query_bbox, attn_mask, h, w):
        # 模拟生成 2 个单木 mask 与得分
        masks = torch.zeros(2, 64, 64)
        masks[0, 10:20, 10:20] = 1.0
        masks[1, 30:40, 30:40] = 1.0
        scores = torch.tensor([0.92, 0.88])
        return masks, scores, None, scores


def test_dinov_adapter_mock_lifecycle(tmp_path: Path) -> None:
    weights = tmp_path / "model_swinT.pth"
    weights.touch()
    backend = FakeDINOvBackend()
    adapter = DINOvReviewAdapter(weights, model_factory=lambda _: backend, conf=0.80)

    caps = adapter.capabilities()
    assert caps["name"] == "dinov"
    assert caps["visual_prompt"] is True
    assert caps["text_prompt"] is False

    ref = np.zeros((64, 64, 3), dtype=np.uint8)
    ref[10:20, 10:20] = 255
    context = adapter.prepare_visual_prompts(ref, [[10, 10, 20, 20]], [0], ["mangrove"])
    assert context.mode == "visual"
    assert context.class_ids == ["mangrove"]
    assert context.encoded is True

    windows = [RasterWindow(0, 0, 64, 64, ref)]
    preds = adapter.predict_batch(windows, context)
    assert len(preds) == 2
    assert preds[0].category_id == "mangrove"
    assert preds[0].score == pytest.approx(0.92, abs=0.01)


def test_dinov_adapter_real_model_smoke() -> None:
    weights = Path(".4estDS/models/dinov/model_swinT.pth")
    if not weights.is_file():
        pytest.skip("DINOv 权重未就绪，跳过真实模型冒烟测试")

    adapter = DINOvReviewAdapter(weights, conf=0.80, device="cpu")
    # 只要能正常加载且 capabilities 正常
    assert adapter.capabilities()["available"] is True
