from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine

from forestds.review.inference_service import ReviewInferenceService
from forestds.review.models import PromptContext, ReviewPrediction
from forestds.review.session_service import ReviewSessionService
from test_review_sessions import PHASE, TIFF, review_db


class CandidateAdapter:
    def capabilities(self):
        return {"name": "candidate"}

    def load(self):
        return None

    def prepare_text_prompts(self, prompts):
        return PromptContext(mode="text", class_ids=[prompts[0]["category_id"]])

    def prepare_visual_prompts(self, reference_image, bboxes, classes, category_ids=None):
        return PromptContext(mode="visual", class_ids=list(category_ids or ["A"]))

    def predict_batch(self, windows, context):
        cat = context.class_ids[0] if context.class_ids else "tree"
        return [ReviewPrediction(
            box_px=[window.x + 2, window.y + 2, window.x + 12, window.y + 12],
            score=0.9,
            category_id=cat,
        ) for window in windows]

    def normalize(self, results, windows, context):
        return list(results)


class OomOnceAdapter(CandidateAdapter):
    def __init__(self):
        self.calls = 0

    def predict_batch(self, windows, context):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("CUDA out of memory")
        return super().predict_batch(windows, context)


def _attach_tiff(url: str, path: Path) -> None:
    transform = Affine(0.01, 0, 0, 0, -0.01, 1)
    with rasterio.open(
        path, "w", driver="GTiff", width=100, height=100, count=3, dtype="uint8", crs="EPSG:4326", transform=transform
    ) as target:
        target.write(np.zeros((3, 100, 100), dtype=np.uint8))
    conn = sqlite3.connect(url.split("///", 1)[1])
    conn.execute(
        "UPDATE tiffs SET path_versions=?, file_name=?, pixel_width=100, pixel_height=100, crs_epsg=4326, geotransform=? "
        "WHERE phase_id=? AND tiff_id=?",
        (json.dumps({"20260718": str(path)}), str(path), json.dumps(list(transform)[:6]), PHASE, TIFF),
    )
    conn.commit()
    conn.close()


def test_attempt_stays_out_of_runs_and_applies_candidates(review_db: tuple[str, Path]) -> None:
    url, drafts = review_db
    image = drafts.parent / "attempt.tif"
    _attach_tiff(url, image)
    sessions = ReviewSessionService(url, draft_root=drafts)
    session = sessions.create(PHASE, TIFF, "fresh")
    service = ReviewInferenceService(url, session_service=sessions, tile_size=64, batch_size=2)
    attempt = service.create_attempt(
        session.session_id,
        revision=0,
        prompt_type="text",
        prompts=[{"category_id": "红树", "display_name": "红树", "model_prompt": "mangrove crown"}],
        scope={"type": "region", "center_px": [50, 50], "side_px": 80},
    )
    completed = service.run_attempt(session.session_id, attempt["attempt_id"], adapter=CandidateAdapter())

    conn = sqlite3.connect(url.split("///", 1)[1])
    try:
        assert conn.execute("SELECT COUNT(*) FROM runs WHERE task_type='review'").fetchone()[0] == 0
    finally:
        conn.close()
    assert completed["status"] == "succeeded"
    assert completed["candidate_count"] == 1

    current_revision = sessions.get(session.session_id).revision
    applied = service.apply_attempt(session.session_id, attempt["attempt_id"], revision=current_revision, threshold=0.8)
    assert applied["status"] == "applied"
    assert len(applied["items"]) == 1


def test_cancel_and_expand_reuse_attempt_configuration(review_db: tuple[str, Path]) -> None:
    url, drafts = review_db
    sessions = ReviewSessionService(url, draft_root=drafts)
    session = sessions.create(PHASE, TIFF, "fresh")
    service = ReviewInferenceService(url, session_service=sessions)
    attempt = service.create_attempt(
        session.session_id,
        revision=0,
        prompt_type="text",
        prompts=[{"category_id": "秋茄", "model_prompt": "kandelia crown"}],
        scope={"type": "region", "center_px": [50, 50], "side_px": 100},
        merge_mode="replace_all",
        threshold=0.4,
    )
    canceled = service.cancel_attempt(session.session_id, attempt["attempt_id"])
    expanded = service.expand_attempt(
        session.session_id,
        attempt["attempt_id"],
        revision=sessions.get(session.session_id).revision,
    )
    assert canceled["status"] == "canceled"
    assert expanded["scope"] == {"type": "full"}
    assert expanded["prompts"] == attempt["prompts"]
    assert expanded["merge_mode"] == "replace_all"
    assert expanded["parent_attempt_id"] == attempt["attempt_id"]


def test_oom_reduces_batch_once_and_keeps_completed_result(review_db: tuple[str, Path]) -> None:
    url, drafts = review_db
    image = drafts.parent / "oom.tif"
    _attach_tiff(url, image)
    sessions = ReviewSessionService(url, draft_root=drafts)
    session = sessions.create(PHASE, TIFF, "fresh")
    service = ReviewInferenceService(url, session_service=sessions, batch_size=4)
    attempt = service.create_attempt(
        session.session_id,
        revision=0,
        prompt_type="text",
        prompts=[{"category_id": "红树", "model_prompt": "mangrove crown"}],
        scope={"type": "full"},
    )
    adapter = OomOnceAdapter()
    result = service.run_attempt(session.session_id, attempt["attempt_id"], adapter=adapter)
    assert result["status"] == "succeeded"
    assert result["oom_batch_reduced"] is True
    assert adapter.calls == 2


def test_build_review_adapter_configurations() -> None:
    from forestds.config import Settings
    from forestds.review.inference_service import build_review_adapter

    # 1. DINOv 变体解析 (显式分离写法)
    dinov_cfg = Settings({
        "review": {
            "adapter": "dinov",
            "variant": "swin_l",
            "models": {
                "dinov": {
                    "variants": {
                        "swin_l": {
                            "weights": ".4estDS/models/dinov/model_swinL.pth",
                            "config": "configs/dinov/dinov_sam_coco_swinl_train.yaml",
                        },
                    },
                },
            },
        },
    })
    dinov_adapter = build_review_adapter(dinov_cfg)
    assert dinov_adapter.capabilities()["name"] == "dinov"
    assert "model_swinL.pth" in dinov_adapter.capabilities()["weights"]

    # 2. YOLOE 变体解析 (简写复合写法: yoloe-26x)
    yoloe_cfg = Settings({
        "review": {
            "adapter": "yoloe-26x",
            "models": {
                "yoloe": {
                    "text_encoder": ".4estDS/models/multimodal/mobileclip2_b.ts",
                    "variants": {
                        "26x": {"weights": ".4estDS/models/multimodal/yoloe-26x-seg.pt"},
                        "26l": {"weights": ".4estDS/models/multimodal/yoloe-26l-seg.pt"},
                    },
                },
            },
        },
    })
    yoloe_adapter = build_review_adapter(yoloe_cfg)
    assert yoloe_adapter.capabilities()["name"] == "yoloe"
    assert "yoloe-26x-seg.pt" in yoloe_adapter.capabilities()["weights"]
    assert "mobileclip2_b.ts" in (yoloe_adapter.capabilities()["mobileclip"] or "")

    # 3. YOLOE 变体解析 (显式分离写法: adapter=yoloe, variant=26l)
    yoloe_26l_cfg = Settings({
        "review": {
            "adapter": "yoloe",
            "variant": "26l",
            "models": {
                "yoloe": {
                    "text_encoder": ".4estDS/models/multimodal/mobileclip2_b.ts",
                    "variants": {
                        "26l": {"weights": ".4estDS/models/multimodal/yoloe-26l-seg.pt"},
                    },
                },
            },
        },
    })
    yoloe_26l_adapter = build_review_adapter(yoloe_26l_cfg)
    assert "yoloe-26l-seg.pt" in yoloe_26l_adapter.capabilities()["weights"]

    # 4. YOLOE 遥感强化变体 (yoloe-26x-m07)
    yoloe_m07_cfg = Settings({
        "review": {
            "adapter": "yoloe-26x-m07",
            "models": {
                "yoloe": {
                    "text_encoder": ".4estDS/models/multimodal/mobileclip2_b.ts",
                    "variants": {
                        "26x-m07": {"weights": ".4estDS/models/multimodal/yoloe-26x-m07.pt"},
                    },
                },
            },
        },
    })
    yoloe_m07_adapter = build_review_adapter(yoloe_m07_cfg)
    assert yoloe_m07_adapter.capabilities()["name"] == "yoloe"
    assert "yoloe-26x-m07.pt" in yoloe_m07_adapter.capabilities()["weights"]

    # 5. 闭集专家模型 (yolo / m07)
    yolo_cfg = Settings({
        "review": {
            "adapter": "yolo",
            "variant": "m07",
            "models": {
                "yolo": {
                    "variants": {
                        "m07": {"weights": ".4estDS/models/m07-yolo26x-7d20f-det-2cls-e152_baseTrain15.pt"},
                    },
                },
            },
        },
    })
    yolo_adapter = build_review_adapter(yolo_cfg)
    assert yolo_adapter.capabilities()["name"] == "yolo"
    assert yolo_adapter.capabilities()["direct_detection"] is True
    assert "m07-yolo26x" in yolo_adapter.capabilities()["weights"]

    # 6. Mock Adapter 解析
    mock_cfg = Settings({"review": {"adapter": "mock_review"}})
    mock_adapter = build_review_adapter(mock_cfg)
    assert mock_adapter.capabilities()["name"] == "mock_review"


def test_create_direct_attempt(review_db: tuple[str, Path]) -> None:
    url, drafts = review_db
    image = drafts.parent / "attempt_direct.tif"
    _attach_tiff(url, image)
    sessions = ReviewSessionService(url, draft_root=drafts)
    session = sessions.create(PHASE, TIFF, "fresh")
    service = ReviewInferenceService(url, session_service=sessions, tile_size=64, batch_size=2)

    attempt = service.create_attempt(
        session.session_id,
        revision=0,
        prompt_type="direct",
        prompts=[],
        scope={"type": "region", "center_px": [50.0, 50.0], "side_px": 50.0},
    )
    assert attempt["prompt_type"] == "direct"
    assert attempt["status"] == "queued"

    # 执行 direct 探测
    result = service.run_attempt(session.session_id, attempt["attempt_id"], adapter=CandidateAdapter())
    assert result["status"] == "succeeded"
    assert result["candidate_count"] > 0




