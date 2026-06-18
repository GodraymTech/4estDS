"""报告层单测（纯标准库 assert，不依赖 pytest fixtures）。

覆盖指标计算与渲染降级，不碰真实文件系统（PDF/图表走临时目录）。
"""
from __future__ import annotations


def _obs(n, species="tree", w=40.0, conf=0.9, slice_size=None, height=None):
    return [
        {
            "species": species, "crown_w_px": w, "crown_h_px": w,
            "crown_area_px": w * w, "confidence": conf,
            "slice_size": slice_size, "height": height,
        }
        for _ in range(n)
    ]


def test_species_composition_sorted_desc():
    from fourestds.report.metrics import species_composition
    obs = _obs(3, "a") + _obs(5, "b") + [{"species": None}]
    comp = species_composition(obs)
    assert list(comp.items())[0] == ("b", 5)
    assert comp["a"] == 3 and comp["unknown"] == 1


def test_density_per_hectare():
    from fourestds.report.metrics import density_per_hectare
    # 100 株 / 10000 m²(=1 ha) = 100 /ha
    assert density_per_hectare(100, 10000.0) == 100.0
    assert density_per_hectare(10, 0) is None
    assert density_per_hectare(10, None) is None


def test_scale_class_breakdown_ratios():
    from fourestds.report.metrics import scale_class_breakdown
    obs = _obs(3, slice_size=512) + _obs(1, slice_size=1024)
    b = scale_class_breakdown(obs)
    assert b["512"]["count"] == 3 and abs(b["512"]["ratio"] - 0.75) < 1e-9
    assert b["1024"]["count"] == 1


def test_compute_report_shape():
    from fourestds.report.metrics import compute_report
    obs = _obs(60, "tree", w=40.0, conf=0.9)
    data = compute_report(obs, tract={"tract_id": "t1", "geo_area": None}, run_id="r1")
    assert data.tree_count == 60
    assert data.crown_w_px["n"] == 60 and data.crown_w_px["median"] == 40.0
    assert data.confidence["n"] == 60
    assert data.density_per_ha is None  # 面积未知 -> 不编造
    assert data.meta["species_richness"] == 1


def test_render_markdown_and_csv_contain_key_sections():
    from fourestds.report.metrics import compute_report
    from fourestds.report.render import to_csv, to_markdown
    obs = _obs(60, "tree", w=40.0, conf=0.9)
    data = compute_report(obs, tract={"tract_id": "t1"}, run_id="r1")
    md = to_markdown(data)
    for key in ["总量与密度", "物种组成", "冠幅与尺寸分布", "离散尺度档占比"]:
        assert key in md, f"missing md section: {key}"
    csv_text = to_csv(data)
    assert "tree_count,60" in csv_text and "crown_w_px.median" in csv_text


def test_pdf_graceful_when_reportlab_missing(monkeypatch=None):
    """reportlab 不可用时 to_pdf 返回 None（不报错）。用 import 遮蔽模拟。"""
    import builtins
    import tempfile
    from pathlib import Path
    from fourestds.report.metrics import compute_report
    from fourestds.report.render import to_pdf
    data = compute_report(_obs(3), tract={"tract_id": "t1"}, run_id="r1")
    real_import = builtins.__import__

    def blocked(name, *a, **k):
        if name.startswith("reportlab"):
            raise ImportError("blocked for test")
        return real_import(name, *a, **k)

    builtins.__import__ = blocked
    try:
        out = to_pdf(data, Path(tempfile.gettempdir()) / "x_should_not_exist.pdf")
    finally:
        builtins.__import__ = real_import
    assert out is None  # 优雅降级，由上层回退 md
