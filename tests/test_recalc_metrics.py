import json
import tempfile
from pathlib import Path
import numpy as np
import pytest

from forestds.db.schema import init_db, get_db_connection
from forestds.tools.recalc_metrics import recalculate_run_metrics


def test_recalculate_run_metrics_no_elevation_skips():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite"
        init_db(db_path)
        conn = get_db_connection(db_path)

        # 插入无高程数据的 run
        conn.execute(
            "INSERT INTO runs (run_id, phase_id, task_type, input_path, params_json, started_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("112233", "20260101", "infer", "/tmp/none.tif", json.dumps({}), "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        conn.commit()
        conn.close()

        res = recalculate_run_metrics("112233", db_url=db_path)
        assert res["status"] == "skipped_no_elevation"
        assert res["updated"] == 0
