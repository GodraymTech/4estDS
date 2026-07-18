from __future__ import annotations

import sqlite3
import json
import multiprocessing
import os
import socket
import sys
import time
import types
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from forestds.review.inference_service import ReviewInferenceService
from test_review_attempts import _attach_tiff
from test_review_sessions import BASE_RUN, PHASE, TIFF, review_db


def _run_server(port: int, db_url: str, home: str) -> None:
    import uvicorn
    from forestds.api.deps import get_db_url
    from forestds.api.main import create_app

    os.environ["forestds_HOME"] = home
    actor = types.SimpleNamespace(send=lambda *args, **kwargs: None)
    fake_actors = types.ModuleType("forestds.worker.actors")
    fake_actors.review_viewport_actor = actor
    fake_actors.review_full_actor = actor
    sys.modules["forestds.worker.actors"] = fake_actors
    app = create_app()
    app.dependency_overrides[get_db_url] = lambda: db_url
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error", lifespan="off", loop="asyncio", http="h11", ws="none")


@contextmanager
def _serve(db_url: str, home: Path):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.close()
    process = multiprocessing.get_context("spawn").Process(
        target=_run_server,
        args=(port, db_url, str(home)),
        daemon=True,
    )
    process.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(200):
        try:
            urllib.request.urlopen(base + "/openapi.json", timeout=0.1).close()
            break
        except (OSError, urllib.error.URLError):
            time.sleep(0.01)
    if not process.is_alive():
        raise RuntimeError("HTTP 测试服务启动失败")
    try:
        yield base
    finally:
        process.terminate()
        process.join(timeout=5)


def _request(base: str, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    payload = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        base + path,
        data=payload,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_effective_area_to_multi_attempt_review_publish_http(
    review_db: tuple[str, Path],
    monkeypatch,
) -> None:
    url, drafts = review_db
    runtime = drafts.parent / "runtime"
    monkeypatch.setenv("forestds_HOME", str(runtime))
    _attach_tiff(url, drafts.parent / "http-review.tif")

    with _serve(url, runtime) as base:
        status, capabilities = _request(base, "GET", "/api/v1/reviews/capabilities")
        assert status == 200, capabilities
        assert capabilities["defaults"]["scope"] == "viewport"
        assert capabilities["limits"]["max_candidates_per_attempt"] == 50_000

        status, current = _request(base, "GET", "/api/v1/tracts/tract-1/effective-area")
        assert status == 200, current
        status, saved = _request(
            base,
            "PUT",
            "/api/v1/tracts/tract-1/effective-area",
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0.01, 0.1], [0.79, 0.1], [0.79, 0.99], [0.01, 0.99], [0.01, 0.1]]],
                },
                "updated_at": current["updated_at"],
            },
        )
        assert status == 200, saved

        status, created = _request(
            base,
            "POST",
            "/api/v1/reviews",
            {"phase_id": PHASE, "tiff_id": TIFF, "mode": "based_on_active"},
        )
        assert status == 200
        session_id = created["session_id"]
        status, page = _request(
            base,
            "GET",
            f"/api/v1/reviews/{session_id}/workspace?bbox=0,0,100,100&limit=1",
        )
        assert status == 200
        assert page["total_items"] == 2
        assert len(page["items"]) == 1

        status, first = _request(
            base,
            "POST",
            f"/api/v1/reviews/{session_id}/attempts",
            {
                "revision": 0,
                "prompt_type": "text",
                "prompts": [{"category_id": "红树", "model_prompt": "mangrove crown"}],
                "scope": {"type": "viewport", "bounds": [0, 0, 0.8, 0.8]},
                "merge_mode": "append",
                "threshold": 0.25,
            },
        )
        assert status == 200
        service = ReviewInferenceService(url)
        first_attempt = service.get_attempt(session_id, first["attempt_id"])
        service._update_attempt(session_id, {
            **first_attempt,
            "status": "succeeded",
            "candidates": [{
                "id": "ai-first", "species": "红树", "confidence": 0.9,
                "box_px": [60, 60, 68, 68], "source": "ai", "confirmed": False, "status": "pending",
            }],
        })
        _, detail = _request(base, "GET", f"/api/v1/reviews/{session_id}")
        status, applied = _request(
            base,
            "POST",
            f"/api/v1/reviews/{session_id}/attempts/{first['attempt_id']}/apply",
            {"revision": detail["revision"], "merge_mode": "append"},
        )
        assert status == 200

        status, second = _request(
            base,
            "POST",
            f"/api/v1/reviews/{session_id}/attempts",
            {
                "revision": applied["revision"],
                "prompt_type": "text",
                "prompts": [{"category_id": "红树", "model_prompt": "mangrove canopy"}],
                "scope": {"type": "full"},
                "merge_mode": "replace_ai_in_scope",
                "threshold": 0.3,
            },
        )
        assert status == 200
        second_attempt = service.get_attempt(session_id, second["attempt_id"])
        service._update_attempt(session_id, {
            **second_attempt,
            "status": "succeeded",
            "candidates": [{
                "id": "ai-second", "species": "红树", "confidence": 0.95,
                "box_px": [62, 62, 70, 70], "source": "ai", "confirmed": False, "status": "pending",
            }],
        })
        _, detail = _request(base, "GET", f"/api/v1/reviews/{session_id}")
        status, replaced = _request(
            base,
            "POST",
            f"/api/v1/reviews/{session_id}/attempts/{second['attempt_id']}/apply",
            {"revision": detail["revision"], "merge_mode": "replace_ai_in_scope"},
        )
        assert status == 200
        assert {item["id"] for item in replaced["items"]} >= {"parent-0", "parent-1", "ai-second"}
        assert "ai-first" not in {item["id"] for item in replaced["items"]}

        status, expanded = _request(
            base,
            "POST",
            f"/api/v1/reviews/{session_id}/attempts/{second['attempt_id']}/expand",
            {"revision": replaced["revision"]},
        )
        assert status == 200
        assert expanded["scope"] == {"type": "full"}

        status, published = _request(base, "POST", f"/api/v1/reviews/{session_id}/publish", {})
        assert status == 200

    conn = sqlite3.connect(url.split("///", 1)[1])
    try:
        active = conn.execute(
            "SELECT active_run_id FROM tiffs WHERE phase_id=? AND tiff_id=?",
            (PHASE, TIFF),
        ).fetchone()[0]
        parent_count = conn.execute(
            "SELECT COUNT(*) FROM tree_observations WHERE run_id=?",
            (BASE_RUN,),
        ).fetchone()[0]
        attempt_runs = conn.execute("SELECT COUNT(*) FROM runs WHERE task_type='review'").fetchone()[0]
    finally:
        conn.close()
    assert active == published["run_id"]
    assert parent_count == 2
    assert attempt_runs == 1
