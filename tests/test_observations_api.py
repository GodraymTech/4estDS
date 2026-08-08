import sqlite3
import pytest

from forestds.api.routers.observations import list_observations
from forestds.db.reader import query_tree_observations_paginated
from forestds.db.schema import init_db


@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_obs.db"
    db_url = str(db_file)
    init_db(db_url)

    conn = sqlite3.connect(db_file)
    try:
        # 预插入测试单木观测数据
        records = [
            (
                f"obs_{i:03d}",
                f"ind_{i:03d}" if i % 2 == 0 else None,
                "run_test_001" if i <= 30 else "run_test_002",
                "ZJ_01#20240101",
                "tiff_test_001",
                "20240101",
                "红树林_秋茄" if i % 3 == 0 else "红树林_桐花树",
                0.5 + (i % 50) * 0.01,
                2.0 + i * 0.1,
                1.5 + (i % 10) * 0.1,
                1.6 + (i % 10) * 0.1,
                2.4 + (i % 10) * 0.2,
                "2024-01-01T12:00:00",
            )
            for i in range(1, 61)  # 共 60 条
        ]
        conn.executemany(
            """
            INSERT INTO tree_observations (
                observation_id, individual_id, run_id, tract_phase_pk,
                tiff_id, phase_id, species, confidence, height,
                crown_width_geo, crown_height_geo, crown_area_geo_est,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            records,
        )
        conn.commit()
    finally:
        conn.close()

    return db_url


def test_observations_pagination(test_db):
    # 默认分页 50 条
    res = query_tree_observations_paginated(tiff_id="tiff_test_001", url=test_db)
    assert res["total"] == 60
    assert len(res["items"]) == 50
    assert res["page"] == 1
    assert res["page_size"] == 50
    assert set(res["available_species"]) == {"红树林_秋茄", "红树林_桐花树"}

    # 切换每页 20 条，第 2 页
    res_p20 = query_tree_observations_paginated(
        tiff_id="tiff_test_001", page=2, page_size=20, url=test_db
    )
    assert res_p20["total"] == 60
    assert len(res_p20["items"]) == 20
    assert res_p20["page"] == 2
    assert res_p20["items"][0]["observation_id"] == "obs_021"


def test_observations_filters_and_sorting(test_db):
    # 按 run_id 过滤
    res_run = query_tree_observations_paginated(run_id="run_test_001", url=test_db)
    assert res_run["total"] == 30

    # 按 species 过滤
    res_sp = query_tree_observations_paginated(species="红树林_秋茄", url=test_db)
    assert res_sp["total"] == 20
    for it in res_sp["items"]:
        assert it["species"] == "红树林_秋茄"

    # 按最低置信度过滤
    res_conf = query_tree_observations_paginated(min_confidence=0.90, url=test_db)
    for it in res_conf["items"]:
        assert it["confidence"] >= 0.90

    # 排序测试 (按树高倒序)
    res_sort = query_tree_observations_paginated(
        sort_by="height", sort_order="desc", page_size=10, url=test_db
    )
    items = res_sort["items"]
    assert items[0]["height"] >= items[1]["height"]


def test_router_list_observations(test_db):
    # 测试 FastAPI router handler 端点
    out = list_observations(
        tiff_id="tiff_test_001",
        run_id="run_test_001",
        page=1,
        page_size=20,
        sort_by="height",
        sort_order="desc",
        db_url=test_db,
    )
    assert out.total == 30
    assert len(out.items) == 20
    assert out.page == 1
    assert out.page_size == 20
    assert out.items[0].height >= out.items[1].height
