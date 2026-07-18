from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from forestds.db.schema import init_db
from forestds.review import ReviewConflict, ReviewSessionService

PHASE = "20260705"
TIFF = "Q0001"
BASE_RUN = "abc123"


@pytest.fixture()
def review_db(tmp_path: Path) -> tuple[str, Path]:
    url = f"sqlite:///{tmp_path / 'review.db'}"
    init_db(url)
    conn = sqlite3.connect(tmp_path / "review.db")
    now = "2026-07-18T00:00:00+00:00"
    conn.execute(
        "INSERT INTO tracts (tract_pk, region_id, tract_id, boundary_geom, effective_area_hm2, boundary_source, coverage_status, created_at, updated_at) "
        "VALUES ('tract-1','region','Q01','POLYGON((0 0,1 0,1 1,0 1,0 0))',123,'manual','full',?,?)",
        (now, now),
    )
    conn.execute(
        "INSERT INTO tract_phases (tract_phase_pk, tract_pk, region_id, tract_id, phase_id, updated_at) "
        "VALUES ('tp-1','tract-1','region','Q01',?,?)",
        (PHASE, now),
    )
    conn.execute(
        "INSERT INTO tiffs (tiff_id, phase_id, tract_phase_pk, file_name, footprint_geom, crs_epsg, geotransform, "
        "pixel_width, pixel_height, active_run_id, created_at, updated_at) "
        "VALUES (?,?, 'tp-1','Q0001.tif','POLYGON((0 0,1 0,1 1,0 1,0 0))',4326,?,100,100,NULL,?,?)",
        (TIFF, PHASE, json.dumps([0.01, 0, 0, 0, -0.01, 1]), now, now),
    )
    conn.execute(
        "INSERT INTO runs (run_id, tract_phase_pk, tiff_id, phase_id, task_type, status, started_at, ended_at, created_at) "
        "VALUES (?, 'tp-1', ?, ?, 'infer', 'succeeded', ?, ?, ?)",
        (BASE_RUN, TIFF, PHASE, now, now, now),
    )
    conn.execute("UPDATE tiffs SET active_run_id=? WHERE tiff_id=? AND phase_id=?", (BASE_RUN, TIFF, PHASE))
    for index in range(2):
        box = [10 + index * 20, 10, 20 + index * 20, 20]
        conn.execute(
            "INSERT INTO tree_observations (observation_id, run_id, tract_phase_pk, tiff_id, phase_id, species, confidence, box_px, created_at) "
            "VALUES (?,?, 'tp-1',?,?, '红树',0.8,?,?)",
            (f"parent-{index}", BASE_RUN, TIFF, PHASE, json.dumps(box), now),
        )
    conn.commit()
    conn.close()
    return url, tmp_path / "drafts"


def test_based_on_active_loads_parent_without_visual_prompts(review_db: tuple[str, Path]) -> None:
    url, drafts = review_db
    service = ReviewSessionService(url, draft_root=drafts)
    session = service.create(PHASE, TIFF, "based_on_active")

    workspace = service.workspace(session.session_id)
    assert session.base_run_id == BASE_RUN
    assert len(workspace.items) == 2
    assert workspace.visual_exemplars == []
    assert workspace.category_catalog[0]["display_name"] == "红树"


def test_from_scratch_and_duplicate_operation_are_recoverable(review_db: tuple[str, Path]) -> None:
    url, drafts = review_db
    service = ReviewSessionService(url, draft_root=drafts)
    session = service.create(PHASE, TIFF, "from_scratch")
    add = {"type": "add", "item": {"box_px": [1, 2, 8, 9], "species": "秋茄"}}
    first = service.apply_operations(session.session_id, 0, "op-1", [add])
    duplicate = service.apply_operations(session.session_id, 0, "op-1", [add])

    restarted = ReviewSessionService(url, draft_root=drafts)
    assert first.revision == duplicate.revision == 1
    assert len(restarted.workspace(session.session_id).items) == 1
    assert restarted.get(session.session_id).revision == 1


def test_revision_conflict_and_undo_redo(review_db: tuple[str, Path]) -> None:
    url, drafts = review_db
    service = ReviewSessionService(url, draft_root=drafts)
    session = service.create(PHASE, TIFF, "based_on_active")
    item_id = service.workspace(session.session_id).items[0]["id"]
    changed = service.apply_operations(
        session.session_id,
        0,
        "rename",
        [{"type": "set_category", "item_id": item_id, "species": "木榄"}],
    )
    with pytest.raises(ReviewConflict) as conflict:
        service.apply_operations(session.session_id, 0, "stale", [{"type": "delete", "item_id": item_id}])
    assert conflict.value.code == "revision_conflict"

    undone = service.undo(session.session_id, changed.revision, "undo-1")
    assert undone.items[0]["species"] == "红树"
    redone = service.redo(session.session_id, undone.revision, "redo-1")
    assert redone.items[0]["species"] == "木榄"


def test_cancel_prevents_further_writes(review_db: tuple[str, Path]) -> None:
    url, drafts = review_db
    service = ReviewSessionService(url, draft_root=drafts)
    session = service.create(PHASE, TIFF, "from_scratch")
    canceled = service.cancel(session.session_id, 0)
    assert canceled.status == "canceled"
    with pytest.raises(ReviewConflict):
        service.apply_operations(session.session_id, 0, "late", [{"type": "add", "item": {"box_px": [0, 0, 1, 1]}}])
