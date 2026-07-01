import sqlite3
import pytest
import unittest.mock as mock
import json
from forestds.db import schema, writer, reader

def test_promote_and_incremental_update(tmp_path):
    db_file = tmp_path / "test.db"
    db_url = f"sqlite:///{db_file}"
    schema.init_db(db_url)
    
    # 1. 模拟地块写入
    tract_id = writer.ensure_tract(
        "202607", "test_loc", name="test_image",
        crs_epsg=4326, url=db_url
    )
    
    # 2. 模拟两个 run
    # Run 1: DSM/DEM
    run1_id = "run_001"
    conn = sqlite3.connect(db_file)
    conn.execute(
        "INSERT INTO run_logs (run_id, status, started_at, task_type) VALUES (?, ?, ?, ?)",
        (run1_id, "succeeded", "2026-07-02T00:00:00", "infer")
    )
    conn.commit()
    conn.close()
    
    # Run 2: LAS
    run2_id = "run_002"
    conn = sqlite3.connect(db_file)
    conn.execute(
        "INSERT INTO run_logs (run_id, status, started_at, task_type) VALUES (?, ?, ?, ?)",
        (run2_id, "succeeded", "2026-07-02T00:10:00", "infer")
    )
    conn.commit()
    conn.close()
    
    # 3. 模拟两批观测数据
    # Obs 1 for Run 1: 2 trees
    # Tree 1 center: (110.0, 20.0), Tree 2 center: (110.01, 20.01)
    class DummyDet:
        def __init__(self, x1, y1, x2, y2, score, label, center):
            self.x1 = x1
            self.y1 = y1
            self.x2 = x2
            self.y2 = y2
            self.score = score
            self.label = label
            self.center = center
            self.width = x2 - x1
            self.height = y2 - y1
            self.extra = {
                "height": 5.0,
                "height_source": "dsm_dem",
                "crown_area_px_est": 100,
                "crown_area_px_real": 80,
                "crown_area_geo_est": 1.0,
                "crown_area_geo_real": 0.8,
                "volume_est": 1.5,
                "volume_real": 1.2
            }
            
    # Mock geotransform and crs
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
            
    # Insert observations for Run 1
    dets_run1 = [
        DummyDet(110.0, 20.0, 110.001, 20.001, 0.9, "tree", (110.0005, 20.0005)),
        DummyDet(110.01, 20.01, 110.011, 20.011, 0.85, "tree", (110.0105, 20.0105))
    ]
    
    with mock.patch("forestds.geo.resolve_geo", return_value=DummyGeo()):
        writer.write_observations(tract_id, run1_id, dets_run1, url=db_url)
        
    # Verify observations inserted
    obs_run1 = reader.fetch_observations(run_id=run1_id, url=db_url)
    assert len(obs_run1) == 2
    
    # Promote Run 1
    writer.promote_run(run1_id, url=db_url)
    assert reader.active_run_for_tract(tract_id, url=db_url) == run1_id
    
    # Check tract_trees populated
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute("SELECT canonical_id, height FROM tract_trees WHERE tract_id=?", (tract_id,))
    rows1 = cursor.fetchall()
    assert len(rows1) == 2
    canonical_id_map1 = {r[0]: r[1] for r in rows1}
    
    # Obs 2 for Run 2: 2 trees
    # Tree 1 moves slightly but overlaps (IoU > 0.5): (110.0001, 20.0001) to (110.0009, 20.0009) -> match!
    # Tree 2 is not detected anymore (removed).
    # Tree 3 is a brand new tree: (110.02, 20.02)
    dets_run2 = [
        DummyDet(110.0001, 20.0001, 110.0009, 20.0009, 0.95, "tree", (110.0005, 20.0005)),
        DummyDet(110.02, 20.02, 110.021, 20.021, 0.88, "tree", (110.0205, 20.0205))
    ]
    dets_run2[0].extra = {
        "height": 5.5,  # Height updated!
        "height_source": "las",
        "crown_area_px_est": 120,
        "crown_area_px_real": 110,
        "crown_area_geo_est": 1.2,
        "crown_area_geo_real": 1.1,
        "volume_est": 2.0,
        "volume_real": 1.8
    }
    dets_run2[1].extra = {
        "height": 4.0,
        "height_source": "las",
        "crown_area_px_est": 50,
        "crown_area_px_real": 40,
        "crown_area_geo_est": 0.5,
        "crown_area_geo_real": 0.4,
        "volume_est": 0.6,
        "volume_real": 0.5
    }
    
    with mock.patch("forestds.geo.resolve_geo", return_value=DummyGeo()):
        writer.write_observations(tract_id, run2_id, dets_run2, url=db_url)
        
    # Promote Run 2
    writer.promote_run(run2_id, url=db_url)
    assert reader.active_run_for_tract(tract_id, url=db_url) == run2_id
    
    # Check tract_trees updated
    cursor.execute("SELECT canonical_id, height, active_run_id FROM tract_trees WHERE tract_id=?", (tract_id,))
    rows2 = cursor.fetchall()
    assert len(rows2) == 2
    
    # Find matching tree
    matched_heights = []
    new_tree_found = False
    for cid, h, arid in rows2:
        if cid in canonical_id_map1:
            # Overlapping tree 1 kept its canonical_id!
            assert h == 5.5  # Height updated from 5.0 to 5.5!
            assert arid == run2_id
            matched_heights.append(h)
        else:
            # New tree got a new canonical_id
            assert h == 4.0
            assert arid == run2_id
            new_tree_found = True
            
    assert len(matched_heights) == 1
    assert new_tree_found
    
    conn.close()
