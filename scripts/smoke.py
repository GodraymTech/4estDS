"""无 pytest 的底座烟雾验证(证明核心可运行)。运行: PYTHONPATH=src python scripts/smoke.py"""
import os
import sys
import tempfile

from fourestds.preprocess import slicing as S
from fourestds.postprocess import wbf
from fourestds import lifecycle

ok = 0


def check(name, cond):
    global ok
    assert cond, f"FAIL: {name}"
    ok += 1
    print(f"  ok  {name}")


print("[slicing]")
check("crown_px_size", S.crown_px_size(4.0, 0.1) == 40.0)
check("trunc small", S.truncation_probability(40, 1024, 256) < 0.05)
check("trunc full", S.truncation_probability(1024, 1024, 128) == 1.0)
scales = S.cluster_scales([20, 22, 21, 80, 82, 79, 200, 205], k=3)
check("cluster len", len(scales) == 3 and scales == sorted(scales))
p = S.optimize_tile_params(40, 1024, 24, 120)
check("optimize detectable", p.tile <= 1024 * 40 / 24)
ii = S.integral_image([[1, 1, 0], [1, 0, 0], [0, 0, 1]])
check("region_sum", S.region_sum(ii, 0, 0, 3, 3) == 4)
check("is_all_nodata", S.is_all_nodata(ii, 2, 0, 1, 2) is True)
tiles = S.build_quadtree(2048, 2048, lambda cx, cy: 1024, 1024, 256)
check("quadtree grid", len(tiles) == 4 and all(t.size == 1024 for t in tiles))
tiles2 = S.build_quadtree(2048, 2048, lambda cx, cy: 200 if cx < 1024 else 1024, 1024, 128)
check("quadtree refine", any(t.size < 1024 for t in tiles2) and any(t.size == 1024 for t in tiles2))

print("[postprocess]")
check("iou", wbf.iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0)
fb, fs = wbf.weighted_boxes_fusion([(0, 0, 10, 10), (1, 1, 11, 11), (100, 100, 110, 110)], [0.9, 0.8, 0.7], 0.5)
check("wbf merge", len(fb) == 2)

print("[lifecycle]")
check("distance", lifecycle.distance((0, 0), (3, 4)) == 5.0)
pairs = lifecycle.match_nearest([(0, 0), (100, 100)], [(1, 1), (101, 99), (500, 500)], 5)
check("match", (0, 0) in pairs and 2 not in {j for _, j in pairs})

print("[db + cli]")
os.environ["FOURESTDS_HOME"] = tempfile.mkdtemp()
from fourestds.db import schema
schema.init_db()
names = set(schema.table_names())
check("db tables", {"run_logs", "tracts", "tract_sources", "tree_observations", "tract_trees", "tree_individuals"}.issubset(names))
from fourestds.cli import main
check("cli db init", main(["db", "init"]) == 0)
check("cli preprocess", main(["preprocess"]) == 0)

print(f"\nALL PASSED: {ok} checks")


# clamp_window 边界兜底
print("[slicing.clamp]")
check("clamp in-bounds", S.clamp_window(0, 0, 1024, 2048, 2048) == (0, 0, 1024, 1024))
check("clamp overflow", S.clamp_window(1800, 1800, 512, 2048, 2048) == (1800, 1800, 248, 248))
check("clamp outside", S.clamp_window(5000, 5000, 512, 2048, 2048)[2:] == (0, 0))
check("clamp invalid", S.clamp_window(0, 0, 0, 2048, 2048) == (0, 0, 0, 0))
print(f"[clamp] checks so far: {ok}")
