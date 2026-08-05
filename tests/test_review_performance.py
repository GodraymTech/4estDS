from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from shapely.geometry import box

from forestds.review.merge_service import ReviewMergeService
from forestds.review.session_service import ReviewSessionService
from test_review_sessions import PHASE, TIFF, review_db


@pytest.mark.parametrize("count", [1_000, 5_000, 10_000])
def test_candidate_merge_baseline_is_subquadratic(count: int) -> None:
    script = """
import json, sys, time
from forestds.review.merge_service import ReviewMergeService, weighted_box_fusion
count = int(sys.argv[1])
candidates = [
    {"id": f"candidate-{index}", "species": "红树", "confidence": 0.8,
     "box_px": [(index % 200) * 20, (index // 200) * 20, (index % 200) * 20 + 8, (index // 200) * 20 + 8],
     "source": "ai", "confirmed": False}
    for index in range(count)
]
started = time.perf_counter()
merged = ReviewMergeService().apply("append", [], candidates, None)
fused = weighted_box_fusion(candidates)
print(json.dumps([len(merged), len(fused), time.perf_counter() - started]))
"""
    for _ in range(3):
        completed = subprocess.run(
            [sys.executable, "-c", script, str(count)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if completed.returncode == 0:
            break
    assert completed.returncode == 0, completed.stderr
    merged_count, fused_count, elapsed = json.loads(completed.stdout)
    assert merged_count == fused_count == count
    assert elapsed < 5.0, f"{count} candidates took {elapsed:.3f}s"


def test_spatial_index_keeps_oversized_box_merge_semantics() -> None:
    existing = [{
        "id": "old", "species": "红树", "confidence": 0.5,
        "box_px": [0, 0, 10_000, 10_000], "source": "ai", "confirmed": False,
    }]
    incoming = [{
        "id": "new", "species": "红树", "confidence": 0.9,
        "box_px": [0, 0, 10_000, 10_000], "source": "ai", "confirmed": False,
    }]
    result = ReviewMergeService().apply("append", existing, incoming, None)
    assert [item["id"] for item in result] == ["new"]


def test_single_edit_uses_delta_history_in_10k_workspace(review_db: tuple[str, Path]) -> None:
    url, drafts = review_db
    service = ReviewSessionService(url, draft_root=drafts)
    session = service.create(PHASE, TIFF, "fresh")
    workspace = service.workspace(session.session_id)
    workspace.items = [
        {
            "id": f"item-{index}",
            "species": "红树",
            "box_px": [index, 0, index + 1, 1],
            "source": "human",
            "confirmed": True,
            "status": "accepted",
        }
        for index in range(10_000)
    ]
    service.drafts.save(session.session_id, workspace)

    started = time.perf_counter()
    patch = service.apply_operations(
        session.session_id,
        0,
        "edit-10k",
        [{"type": "update", "item_id": "item-5000", "patch": {"species": "秋茄"}}],
    )
    elapsed = time.perf_counter() - started
    saved = service.workspace(session.session_id)

    assert patch.replace_all is False
    assert [item["id"] for item in patch.changed_items] == ["item-5000"]
    assert saved.undo_stack[-1]["_kind"] == "delta"
    assert len(json.dumps(saved.undo_stack[-1], ensure_ascii=False)) < 1_000
    assert elapsed < 3.0, f"10k single edit took {elapsed:.3f}s"


def test_window_classification_baseline_avoids_full_resolution_mask() -> None:
    from forestds.effective_area.windows import EffectiveWindowFilter

    window_filter = EffectiveWindowFilter.from_pixel_geometry(box(1_000, 1_000, 9_000, 9_000))
    started = time.perf_counter()
    results = [
        window_filter.classify((x, y, 100, 100))
        for y in range(0, 10_000, 100)
        for x in range(0, 10_000, 100)
    ]
    elapsed = time.perf_counter() - started

    assert len(results) == 10_000
    assert results.count("outside") > 3_000
    assert window_filter.local_mask((0, 0, 100, 100)) is None
    assert elapsed < 2.0, f"10k windows took {elapsed:.3f}s"
