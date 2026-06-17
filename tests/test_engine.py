"""阶段三:检测器注册表 + 推理编排器端到端测试(mock 后端,无重依赖)。"""
import pytest

from fourestds.detect import Window, available_backends, get_detector
from fourestds.engine import RasterImageSource, SyntheticImageSource, run_inference


def test_registry_lists_builtin_backends():
    backends = available_backends()
    assert {"yolo12", "rtdetr", "mock"} <= set(backends)


def test_mock_detector_local_coords():
    det = get_detector("mock", trees=[(1500, 1500, 40)])
    # 读窗从 (1024,1024) 开始 -> 树应在内部坐标 (476,476) 附近
    out = det.predict(Window(x=1024, y=1024, w=1024, h=1024))
    assert len(out) == 1
    cx, cy = out.items[0].center
    assert abs(cx - 476) < 1e-6 and abs(cy - 476) < 1e-6


def test_mock_detector_skips_outside():
    det = get_detector("mock", trees=[(50, 50, 40)])
    out = det.predict(Window(x=1024, y=1024, w=1024, h=1024))
    assert len(out) == 0


def test_run_inference_end_to_end_offsets_to_global():
    det = get_detector("mock", trees=[(1500, 1500, 40)])
    src = SyntheticImageSource(width=2048, height=2048)
    res = run_inference(src, det, root_size=1024, min_size=256)
    assert res.tiles_total == 4  # 2x2 均匀网格
    assert res.fused_count == 1
    cx, cy = res.detections.items[0].center
    assert abs(cx - 1500) < 1.0 and abs(cy - 1500) < 1.0


def test_run_inference_counts_all_trees_once():
    trees = [(300, 300, 30), (1300, 300, 30), (300, 1300, 30), (1700, 1700, 30)]
    det = get_detector("mock", trees=trees)
    src = SyntheticImageSource(width=2048, height=2048)
    res = run_inference(src, det, root_size=1024, min_size=256)
    # 非重叠网格:每棵树恰好被计一次
    assert res.raw_count == 4
    assert res.fused_count == 4


def test_run_inference_handles_border_clamp():
    # 非 1024 整倍尺寸 -> 边界 tile 被 clamp,不崩溃
    det = get_detector("mock", trees=[(1400, 1400, 30)])
    src = SyntheticImageSource(width=1500, height=1500)
    res = run_inference(src, det, root_size=1024, min_size=256)
    assert res.fused_count == 1


def test_predict_batch_default_matches_predict():
    # BaseDetector.predict_batch 默认逐窗调用 predict,结果一致
    det = get_detector("mock", trees=[(1500, 1500, 40), (1600, 1600, 30)])
    w = Window(x=1024, y=1024, w=1024, h=1024)
    batched = det.predict_batch([w, w])
    assert len(batched) == 2
    assert len(batched[0]) == len(det.predict(w)) == 2


def test_run_inference_respects_batch_size():
    # 不同 batch_size 不影响结果(仅影响吞吐/内存)
    trees = [(300, 300, 30), (1300, 300, 30), (1700, 1700, 30)]
    det = get_detector("mock", trees=trees)
    src = SyntheticImageSource(width=2048, height=2048)
    r1 = run_inference(src, det, root_size=1024, min_size=256, batch_size=1)
    r8 = run_inference(src, det, root_size=1024, min_size=256, batch_size=8)
    assert r1.fused_count == r8.fused_count == 3


def test_real_backends_raise_clean_error_without_ultralytics():
    # 沙箱无 ultralytics:load() 应报出带安装指引的清晰错误
    for arch in ("yolo12", "rtdetr"):
        det = get_detector(arch)
        with pytest.raises(ImportError, match="ultralytics"):
            det.load()


def test_raster_image_source_pillow_fallback(tmp_path):
    # 无 rasterio 时回退 Pillow:能正确读出 RGB 窗口
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")
    arr = (np.random.default_rng(0).random((64, 80, 3)) * 255).astype("uint8")
    p = tmp_path / "tile.png"
    Image.fromarray(arr).save(p)
    src = RasterImageSource(str(p))
    assert (src.width, src.height) == (80, 64)
    win = src.read_window(10, 5, 20, 16)
    assert win.shape == (16, 20, 3)
    src.close()


def test_run_inference_preserves_species_labels():
    # 不同物种的检出应保留各自标签(不被融合成统一 "tree")
    trees = [(300, 300, 40, "avicennia"), (1700, 1700, 30, "sonneratia")]
    det = get_detector("mock", trees=trees)
    src = SyntheticImageSource(width=2048, height=2048)
    res = run_inference(src, det, root_size=1024, min_size=256)
    assert res.fused_count == 2
    assert {d.label for d in res.detections.items} == {"avicennia", "sonneratia"}


def test_overlap_dedups_boundary_tree():
    # 跨 tile 边界附近的树:无外扩 -> 只被一个读窗看到;外扩 -> 两个读窗都看到,
    # 但 WBF 去重后仍为 1 棵
    det = get_detector("mock", trees=[(1100, 300, 40)])
    src = SyntheticImageSource(width=2048, height=2048)
    no_ov = run_inference(src, det, root_size=1024, min_size=256, overlap_px=0)
    ov = run_inference(src, det, root_size=1024, min_size=256, overlap_px=128)
    assert (no_ov.raw_count, no_ov.fused_count) == (1, 1)
    assert ov.raw_count == 2 and ov.fused_count == 1
    assert ov.detections.items[0].extra.get("support") == 2


def test_truncated_boundary_box_still_counted():
    # 无外扩时,跨 tile 边界的树被标记截断并降权;不应因降权而丢失
    det = get_detector("mock", trees=[(1024, 300, 40)])
    src = SyntheticImageSource(width=2048, height=2048)
    res = run_inference(src, det, root_size=1024, min_size=256, overlap_px=0)
    assert res.raw_count == 1 and res.fused_count == 1
    cx, cy = res.detections.items[0].center
    assert abs(cx - 1024) < 5.0 and abs(cy - 300) < 2.0
