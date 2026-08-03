import sqlite3
import unittest.mock as mock

from forestds.db import reader, schema, writer


class DummyGeo:
    def gsd_m(self):
        return 0.05

    def pixel_area_m2(self):
        return 0.0025

    @property
    def transform(self):
        class DummyTransform:
            def pixel_to_world(self, px, py):
                return px, py

        return DummyTransform()


class DummyDet:
    def __init__(self, x1, y1, x2, y2, score, label, center, extra=None):
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.score = score
        self.label = label
        self.center = center
        self.width = x2 - x1
        self.height = y2 - y1
        self.extra = extra or {}


def test_promote_switches_active_run_without_tree_join_table(tmp_path):
    db_file = tmp_path / "test.db"
    db_url = f"sqlite:///{db_file}"
    schema.init_db(db_url)

    tract_id = writer.ensure_tract(
        "20260701",
        "Q12",
        crs_epsg=4326,
        url=db_url,
    )

    conn = sqlite3.connect(db_file)
    tract_phase_pk = conn.execute(
        "SELECT tract_phase_pk FROM tract_phases WHERE tract_id=? AND phase_id=?",
        (tract_id, "20260701"),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO tiffs "
        "(tiff_id, phase_id, tract_phase_pk, file_name, path_versions, footprint_geom, "
        "footprint_area_hm2, area_hm2, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, '{}', ?, ?, ?, ?, ?)",
        (
            "tif01",
            "20260701",
            tract_phase_pk,
            "Q12.tif",
            "POLYGON ((110 20, 111 20, 111 21, 110 21, 110 20))",
            1.0,
            1.0,
            "2026-07-01T00:00:00",
            "2026-07-01T00:00:00",
        ),
    )
    conn.execute(
        "INSERT INTO runs "
        "(run_id, tract_phase_pk, tiff_id, phase_id, status, started_at, created_at, task_type) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "aaa111",
            tract_phase_pk,
            "tif01",
            "20260701",
            "succeeded",
            "2026-07-02T00:00:00",
            "2026-07-02T00:00:00",
            "infer",
        ),
    )
    conn.execute(
        "INSERT INTO runs "
        "(run_id, tract_phase_pk, tiff_id, phase_id, status, started_at, created_at, task_type) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "bbb222",
            tract_phase_pk,
            "tif01",
            "20260701",
            "succeeded",
            "2026-07-02T00:10:00",
            "2026-07-02T00:10:00",
            "infer",
        ),
    )
    conn.commit()
    conn.close()

    dets_run1 = [
        DummyDet(
            110.0,
            20.0,
            110.001,
            20.001,
            0.9,
            "tree",
            (110.0005, 20.0005),
            {
                "height": 5.0,
                "height_source": "dsm_dem",
                "crown_area_px_real": 80,
                "crown_area_geo_est": 1.0,
                "crown_area_geo_real": 0.8,
                "volume_est": 1.5,
                "volume_real": 1.2,
            },
        )
    ]

    with mock.patch("forestds.geo.resolve_geo", return_value=DummyGeo()):
        writer.write_observations(tract_id, "aaa111", dets_run1, url=db_url, phase_id="20260701")

    writer.promote_run("aaa111", url=db_url)
    assert reader.active_run_for_tract(tract_id, url=db_url) == "aaa111"
    obs_run1 = reader.fetch_observations(run_id="aaa111", tract_id=tract_id, url=db_url)
    assert len(obs_run1) == 1
    assert obs_run1[0]["crown_area_px"] == 80

    dets_run2 = [
        DummyDet(
            110.02,
            20.02,
            110.021,
            20.021,
            0.88,
            "tree",
            (110.0205, 20.0205),
            {
                "height": 4.0,
                "height_source": "las",
                "crown_area_px_real": 40,
                "crown_area_geo_est": 0.5,
                "crown_area_geo_real": 0.4,
                "volume_est": 0.6,
                "volume_real": 0.5,
            },
        )
    ]

    with mock.patch("forestds.geo.resolve_geo", return_value=DummyGeo()):
        writer.write_observations(tract_id, "bbb222", dets_run2, url=db_url, phase_id="20260701")

    writer.promote_run("bbb222", url=db_url)
    assert reader.active_run_for_tract(tract_id, url=db_url) == "bbb222"
    assert len(reader.fetch_observations(run_id="aaa111", tract_id=tract_id, url=db_url)) == 1
    assert len(reader.fetch_observations(run_id="bbb222", tract_id=tract_id, url=db_url)) == 1
