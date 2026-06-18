"""批量处理单测（纯标准库 assert）。

用依赖注入（SyntheticImageSource + mock）验证批量编排，不依赖 GPU/真实影像。
persist=False，不碰数据库。
"""
from __future__ import annotations

import tempfile
from pathlib import Path


def test_discover_inputs_filters_and_sorts():
    from fourestds.engine.batch import discover_inputs
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        for name in ["b.tif", "a.tif", "c.png", "note.txt", "d.TIFF"]:
            (base / name).write_bytes(b"x")
        found = discover_inputs(base, "*")
        names = [p.name for p in found]
        assert "note.txt" not in names
        assert names == sorted(names)  # 排序
        assert "d.TIFF" in names and "c.png" in names


def test_discover_inputs_missing_dir_raises():
    from fourestds.engine.batch import discover_inputs
    try:
        discover_inputs("/no/such/dir/4estds", "*.tif")
        assert False, "should raise FileNotFoundError"
    except FileNotFoundError:
        pass


def test_run_batch_di_no_persist():
    from fourestds.detect import get_detector
    from fourestds.engine import SyntheticImageSource, run_batch
    inputs = [Path("/tmp/plotA.tif"), Path("/tmp/plotB.tif")]
    det = get_detector("mock", trees=[(500, 500, 40), (2600, 2600, 30)])
    res = run_batch(
        inputs, det,
        acquisition_time="202406",
        source_factory=lambda p: SyntheticImageSource(4096, 4096),
        persist=False,
        run_kwargs={"root_size": 1024, "min_size": 256},
    )
    assert res.total == 2 and res.succeeded == 2 and res.failed == 0
    assert res.total_trees == 4
    assert all(i.status == "succeeded" for i in res.items)


def test_run_batch_single_failure_does_not_abort():
    """单图失败不应中断整批。"""
    from fourestds.detect import get_detector
    from fourestds.engine import SyntheticImageSource, run_batch

    def factory(p: Path):
        if p.name == "bad.tif":
            raise RuntimeError("损坏的影像")
        return SyntheticImageSource(4096, 4096)

    inputs = [Path("/tmp/ok.tif"), Path("/tmp/bad.tif")]
    det = get_detector("mock", trees=[(500, 500, 40)])
    res = run_batch(
        inputs, det, source_factory=factory, persist=False,
        run_kwargs={"root_size": 1024, "min_size": 256},
    )
    assert res.succeeded == 1 and res.failed == 1
    bad = [i for i in res.items if i.location == "bad"][0]
    assert bad.status == "failed" and "损坏" in (bad.error or "")
