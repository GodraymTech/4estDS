from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from forestds.review import ReviewPublishService, ReviewSessionService, ReviewValidationError
from test_review_sessions import BASE_RUN, PHASE, TIFF, review_db


def _connection(url: str) -> sqlite3.Connection:
    conn = sqlite3.connect(url.split("///", 1)[1])
    conn.row_factory = sqlite3.Row
    return conn


def test_publish_creates_review_run_and_switches_only_target_tiff(review_db: tuple[str, Path]) -> None:
    url, drafts = review_db
    sessions = ReviewSessionService(url, draft_root=drafts)
    session = sessions.create(PHASE, TIFF, "inherit")
    result = ReviewPublishService(url, session_service=sessions).publish(session.session_id)

    conn = _connection(url)
    try:
        active = conn.execute("SELECT active_run_id FROM tiffs WHERE phase_id=? AND tiff_id=?", (PHASE, TIFF)).fetchone()[0]
        run = conn.execute("SELECT * FROM runs WHERE run_id=?", (result["run_id"],)).fetchone()
        parent_count = conn.execute("SELECT COUNT(*) FROM tree_observations WHERE run_id=?", (BASE_RUN,)).fetchone()[0]
        review_count = conn.execute("SELECT COUNT(*) FROM tree_observations WHERE run_id=?", (result["run_id"],)).fetchone()[0]
    finally:
        conn.close()
    assert active == result["run_id"]
    assert run["task_type"] == "review"
    assert run["parent_run_id"] == BASE_RUN
    assert parent_count == review_count == 2
    assert sessions.get(session.session_id).status == "published"


def test_publish_failure_rolls_back_run_observations_active_and_session(review_db: tuple[str, Path]) -> None:
    url, drafts = review_db
    sessions = ReviewSessionService(url, draft_root=drafts)
    session = sessions.create(PHASE, TIFF, "inherit")

    def fail(_conn, _run_id):
        raise RuntimeError("injected")

    with pytest.raises(RuntimeError, match="injected"):
        ReviewPublishService(url, session_service=sessions, after_observations=fail).publish(session.session_id)

    conn = _connection(url)
    try:
        assert conn.execute("SELECT active_run_id FROM tiffs WHERE phase_id=? AND tiff_id=?", (PHASE, TIFF)).fetchone()[0] == BASE_RUN
        assert conn.execute("SELECT COUNT(*) FROM runs WHERE task_type='review'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM tree_observations WHERE run_id<>?", (BASE_RUN,)).fetchone()[0] == 0
    finally:
        conn.close()
    assert sessions.get(session.session_id).status == "active"


def test_publish_rejects_missing_category_and_outside_effective_area(review_db: tuple[str, Path]) -> None:
    url, drafts = review_db
    sessions = ReviewSessionService(url, draft_root=drafts)
    empty = sessions.create(PHASE, TIFF, "fresh")
    patch = sessions.apply_operations(
        empty.session_id,
        0,
        "add-empty",
        [{"type": "add", "item": {"box_px": [1, 1, 2, 2], "species": ""}}],
    )
    with pytest.raises(ReviewValidationError) as missing:
        ReviewPublishService(url, session_service=sessions).publish(empty.session_id)
    assert missing.value.code == "category_required"

    based = sessions.create(PHASE, TIFF, "inherit")
    item_id = sessions.workspace(based.session_id).items[0]["id"]
    sessions.apply_operations(
        based.session_id,
        0,
        "outside",
        [{"type": "update", "item_id": item_id, "patch": {"box_px": [110, 110, 120, 120]}}],
    )
    with pytest.raises(ReviewValidationError) as outside:
        ReviewPublishService(url, session_service=sessions).publish(based.session_id)
    assert outside.value.code == "outside_effective_area"
