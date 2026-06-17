"""阶段三:检测器注册表 + 推理编排器端到端测试(mock 后端,无重依赖)。"""
from fourestds.detect import Window, available_backends, get_detector
from fourestds.engine import SyntheticImageSource, run_inference


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
