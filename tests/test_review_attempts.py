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
        return [ReviewPrediction(
            box_px=[window.x + 2, window.y + 2, window.x + 12, window.y + 12],
            score=0.9,
            category_id=context.class_ids[0],
            source_window=(window.x, window.y, window.width, window.height),
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
    applied = service.apply_attempt(session.session_id, attempt["attempt_id"], revision=current_revision)
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
