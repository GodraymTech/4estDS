import sqlite3
import pytest

from forestds.api.routers.assets import patch_tiff, AssetPatch
from forestds.db import writer
from forestds.db.schema import init_db


@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_relocate.db"
    db_url = str(db_file)
    init_db(db_url)

    conn = sqlite3.connect(db_file)
    try:
        # 创建已知地块 C01
        tract_pk = writer.ensure_tract_identity(
            conn,
            region_id="CN440811",
            tract_id="C01",
            city="湛江市",
            county="麻章区",
            town="湖光镇",
        )
        phase_pk = "phase#C01#20260711"
        conn.execute(
            "INSERT INTO tract_phases (tract_phase_pk, tract_pk, region_id, tract_id, phase_id, updated_at) "
            "VALUES (?, ?, 'CN440811', 'C01', '20260711', datetime('now'))",
            (phase_pk, tract_pk),
        )
        geom = '{"type":"Polygon","coordinates":[[[110.0,21.0],[110.1,21.0],[110.1,21.1],[110.0,21.1],[110.0,21.0]]]}'
        # 插入两张影像 c28fe 和 40c2f
        conn.execute(
            "INSERT INTO tiffs (tiff_id, phase_id, tract_phase_pk, file_name, path_versions, tiff_type, footprint_geom, created_at, updated_at) "
            "VALUES ('c28fe', '20260711', ?, 't1', '{}', 'COG', ?, datetime('now'), datetime('now'))",
            (phase_pk, geom),
        )
        conn.execute(
            "INSERT INTO tiffs (tiff_id, phase_id, tract_phase_pk, file_name, path_versions, tiff_type, footprint_geom, created_at, updated_at) "
            "VALUES ('40c2f', '20260711', ?, 't2', '{}', 'COG', ?, datetime('now'), datetime('now'))",
            (phase_pk, geom),
        )
        conn.commit()
    finally:
        conn.close()

    return db_url


def test_relocate_tiff_from_known_tract(test_db):
    # 将 c28fe 单独迁移到地块 C02
    patch_tiff(
        phase_id="20260711",
        tiff_id="c28fe",
        body=AssetPatch(
            city="湛江市",
            county="麻章区",
            tract_id="C02",
        ),
        db_url=test_db,
    )

    conn = sqlite3.connect(test_db.replace("sqlite:///", ""))
    conn.row_factory = sqlite3.Row
    try:
        # 40c2f 依然留在 C01
        t2 = conn.execute(
            "SELECT tf.tiff_id, tr.tract_id FROM tiffs tf "
            "JOIN tract_phases tp ON tp.tract_phase_pk=tf.tract_phase_pk "
            "JOIN tracts tr ON tr.tract_pk=tp.tract_pk "
            "WHERE tf.tiff_id='40c2f'"
        ).fetchone()
        assert t2["tract_id"] == "C01"

        # c28fe 迁移到了 C02
        t1 = conn.execute(
            "SELECT tf.tiff_id, tr.tract_id FROM tiffs tf "
            "JOIN tract_phases tp ON tp.tract_phase_pk=tf.tract_phase_pk "
            "JOIN tracts tr ON tr.tract_pk=tp.tract_pk "
            "WHERE tf.tiff_id='c28fe'"
        ).fetchone()
        assert t1["tract_id"] == "C02"
    finally:
        conn.close()
