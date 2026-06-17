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


# 阶段三:推理引擎端到端(mock)
print("[engine.infer]")
from fourestds.detect import available_backends, get_detector  # noqa: E402
from fourestds.engine import SyntheticImageSource, run_inference  # noqa: E402

check("backends list", {"yolo12", "rtdetr", "mock"} <= set(available_backends()))
_det = get_detector("mock", trees=[(1500, 1500, 40)])
_src = SyntheticImageSource(width=2048, height=2048)
_res = run_inference(_src, _det, root_size=1024, min_size=256)
check("engine tiles", _res.tiles_total == 4)
check("engine fused==1", _res.fused_count == 1)
_c = _res.detections.items[0].center
check("engine global coords", abs(_c[0] - 1500) < 1.0 and abs(_c[1] - 1500) < 1.0)
_det2 = get_detector("mock", trees=[(300, 300, 30), (1300, 300, 30), (1700, 1700, 30)])
_res2 = run_inference(_src, _det2, root_size=1024, min_size=256)
check("engine counts all", _res2.fused_count == 3)

# predict_batch 默认逐窗 == predict;batch_size 不影响结果
from fourestds.detect import Window  # noqa: E402
_w = Window(x=1024, y=1024, w=1024, h=1024)
_batched = get_detector("mock", trees=[(1500, 1500, 40)]).predict_batch([_w, _w])
check("predict_batch default", len(_batched) == 2 and len(_batched[0]) == 1)
_rb = run_inference(_src, _det2, root_size=1024, min_size=256, batch_size=1)
check("batch_size invariant", _rb.fused_count == 3)

# 真实后端缺 ultralytics 时报出清晰错误
for _arch in ("yolo12", "rtdetr"):
    try:
        get_detector(_arch).load()
        _clean = False
    except ImportError as _e:
        _clean = "ultralytics" in str(_e)
    except Exception:
        _clean = False
    check(f"{_arch} clean import error", _clean)

# RasterImageSource Pillow 回退实读(沙箱有 numpy + Pillow)
try:
    import numpy as _np
    from PIL import Image as _Image
    from fourestds.engine import RasterImageSource
    _arr = (_np.random.default_rng(0).random((64, 80, 3)) * 255).astype("uint8")
    _pp = os.path.join(tempfile.mkdtemp(), "tile.png")
    _Image.fromarray(_arr).save(_pp)
    _rsrc = RasterImageSource(_pp)
    _win = _rsrc.read_window(10, 5, 20, 16)
    check("raster pillow read", (_rsrc.width, _rsrc.height) == (80, 64) and _win.shape == (16, 20, 3))
    _rsrc.close()
except ImportError:
    print("  skip raster pillow read (no numpy/PIL)")

print(f"[engine] checks so far: {ok}")


# 阶段五:尺度感知 WBF(标签/权重/conf_type/中心合并) + 边界去重
print("[postprocess.stage5]")
_lab = wbf.fuse([(0, 0, 10, 10), (1, 1, 11, 11)], [0.9, 0.8], labels=["avicennia", "sonneratia"], iou_thr=0.5)
check("fuse label-aware split", len(_lab) == 2 and all(f.support == 1 for f in _lab))
_same = wbf.fuse([(0, 0, 10, 10), (1, 1, 11, 11)], [0.9, 0.8], labels=["tree", "tree"], iou_thr=0.5)
check("fuse same-label merge support", len(_same) == 1 and _same[0].support == 2)
_mx = wbf.fuse([(0, 0, 10, 10), (1, 1, 11, 11)], [0.9, 0.5], iou_thr=0.5, conf_type="max")
_av = wbf.fuse([(0, 0, 10, 10), (1, 1, 11, 11)], [0.9, 0.5], iou_thr=0.5, conf_type="avg")
check("fuse conf_type max/avg", abs(_mx[0].score - 0.9) < 1e-9 and abs(_av[0].score - 0.7) < 1e-9)
_wt = wbf.fuse([(0, 0, 10, 10), (2, 2, 12, 12)], [0.9, 0.9], weights=[1.0, 0.01], iou_thr=0.3)
check("fuse weight pulls coords", len(_wt) == 1 and _wt[0].box[0] < 0.5)
_cm = wbf.fuse([(0, 0, 10, 10), (8, 0, 18, 10)], [0.8, 0.8], iou_thr=0.5, center_merge_frac=0.7)
check("fuse center-merge", len(_cm) == 1 and _cm[0].support == 2)

print("[engine.stage5]")
_sp = get_detector("mock", trees=[(300, 300, 40, "avicennia"), (1700, 1700, 30, "sonneratia")])
_rsp = run_inference(_src, _sp, root_size=1024, min_size=256)
check("engine labels preserved", {d.label for d in _rsp.detections.items} == {"avicennia", "sonneratia"})
_bt = get_detector("mock", trees=[(1100, 300, 40)])
_noov = run_inference(_src, _bt, root_size=1024, min_size=256, overlap_px=0)
_yesov = run_inference(_src, _bt, root_size=1024, min_size=256, overlap_px=128)
check("engine no-overlap 1/1", (_noov.raw_count, _noov.fused_count) == (1, 1))
check("engine overlap dedup 2->1", _yesov.raw_count == 2 and _yesov.fused_count == 1)
check("engine fused support==2", _yesov.detections.items[0].extra.get("support") == 2)
check("engine fusion meta", _yesov.detections.meta.get("fusion") == "wbf")
print(f"[stage5] checks so far: {ok}")
