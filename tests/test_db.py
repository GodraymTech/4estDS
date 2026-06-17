"""DB 三层模型建表测试(标准库 sqlite3,无重依赖)。"""
import os

import pytest


@pytest.fixture()
def temp_home(tmp_path, monkeypatch):
    monkeypatch.setenv("FOURESTDS_HOME", str(tmp_path / ".4estDS"))
    # 重新导入以生效(paths 读环境变量是动态的,无需 reload)
    yield tmp_path


def test_init_db_creates_all_tables(temp_home):
    from fourestds.db import schema

    path = schema.init_db()
    assert os.path.exists(path)
    names = set(schema.table_names())
    expected = {
        "run_logs",
        "tree_individuals",
        "tracts",
        "tract_sources",
        "tree_observations",
        "tract_trees",
    }
    assert expected.issubset(names)


def test_tracts_unique_constraint(temp_home):
    import sqlite3

    from fourestds.db import schema

    path = schema.init_db()
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO tracts (tract_id, acquisition_time, location) VALUES (?,?,?)",
            ("t1", "202401", "siteA"),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO tracts (tract_id, acquisition_time, location) VALUES (?,?,?)",
                ("t2", "202401", "siteA"),  # 同 (时相,位置) -> 冲突
            )
            conn.commit()
    finally:
        conn.close()
