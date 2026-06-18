"""阶段七 多源融合(RGB × CHM 树高)单测（纯标准库 assert）。

覆盖：CHM=DSM-DEM(nodata/负值)、标量树高、窗口采样统计量/越界/全nodata、
CHMSampler 像素对齐与仿射配准、超限异常值、annotate 写 extra。
"""
from __future__ import annotations

import numpy as np


def test_chm_from_dsm_dem_nodata_and_clip():
    from fourestds.fusion import chm_from_dsm_dem
    dsm = np.array([[10.0, 11.0, -999.0], [12.0, 13.0, 14.0]], dtype="float32")
    dem = np.array([[2.0, 2.0, 2.0], [20.0, 3.0, 3.0]], dtype="float32")
    chm = chm_from_dsm_dem(dsm, dem, dsm_nodata=-999.0)
    assert np.isnan(chm[0, 2])          # nodata -> NaN
    assert chm[1, 0] == 0.0             # 负高裁到 0
    assert chm[0, 0] == 8.0 and chm[0, 1] == 9.0


def test_chm_shape_mismatch_raises():
    from fourestds.fusion import chm_from_dsm_dem
    try:
        chm_from_dsm_dem(np.zeros((2, 2)), np.zeros((3, 3)))
    except ValueError:
        return
    raise AssertionError("尺寸不一致应报 ValueError")


def test_tree_height_from_chm_scalar():
    from fourestds.fusion import tree_height_from_chm
    assert tree_height_from_chm(15, 3) == 12.0
    assert tree_height_from_chm(3, 15) == 0.0  # 负值裁 0


def test_sample_height_stats_and_edges():
    from fourestds.fusion import sample_height
    a = np.full((20, 20), 5.0, dtype="float32")
    a[10, 10] = 25.0
    a[0:3, 0:3] = np.nan
    assert sample_height(a, 10, 10, half_win=2, stat="max") == 25.0
    assert sample_height(a, 10, 10, half_win=0, stat="max") == 25.0
    assert sample_height(a, 1, 1, half_win=1) is None        # 全 nodata
    assert sample_height(a, 100, 100) is None                # 越界
    assert sample_height(a, 5, 5, stat="median") == 5.0


def test_chmsampler_pixel_aligned():
    from fourestds.fusion import CHMSampler
    from fourestds.detect import Detection
    chm = np.full((100, 100), 8.0, dtype="float32")
    chm[50, 50] = 18.0
    smp = CHMSampler(chm=chm, stat="max")
    d = Detection(40, 40, 60, 60, 0.9)  # center (50,50)
    h, src = smp.height_for_detection(d)
    assert h == 18.0 and src == "chm"


def test_chmsampler_geo_coregistered():
    """RGB 0.5m/px 与 CHM 1.0m/px 同世界原点,跨分辨率配准。"""
    from fourestds.fusion import CHMSampler
    from fourestds.detect import Detection
    from fourestds.geo import Affine
    rgb_aff = Affine.from_pixel_scale(0.5, 0.5, 1000.0, 5000.0)
    chm_aff = Affine.from_pixel_scale(1.0, 1.0, 1000.0, 5000.0)
    chm = np.zeros((50, 50), dtype="float32")
    chm[10, 10] = 22.0
    smp = CHMSampler(chm=chm, chm_transform=chm_aff, rgb_transform=rgb_aff, stat="max")
    # CHM px(10,10) <=> world(1010,4990) <=> RGB px(20,20)
    d = Detection(16, 16, 24, 24, 0.9)  # center (20,20)
    h, src = smp.height_for_detection(d)
    assert h == 22.0 and src == "chm"


def test_chmsampler_outlier_and_annotate():
    from fourestds.fusion import CHMSampler
    from fourestds.detect import Detection
    chm = np.full((30, 30), 200.0, dtype="float32")  # 荒賬高度
    smp = CHMSampler(chm=chm)
    d = Detection(10, 10, 14, 14, 0.9)
    summary = smp.annotate([d])
    assert d.extra["height"] is None
    assert d.extra["height_source"] == "chm_outlier"
    assert summary["n_outlier"] == 1 and summary["n_with_height"] == 0


def test_chmsampler_nodata_source():
    from fourestds.fusion import CHMSampler
    from fourestds.detect import Detection
    chm = np.full((30, 30), np.nan, dtype="float32")
    smp = CHMSampler(chm=chm)
    d = Detection(10, 10, 14, 14, 0.9)
    h, src = smp.height_for_detection(d)
    assert h is None and src == "chm_nodata"


def test_affine_pixel_world_roundtrip():
    from fourestds.geo import Affine
    aff = Affine.from_pixel_scale(0.5, 0.5, 1000.0, 5000.0)
    wx, wy = aff.pixel_to_world(20, 20)
    col, row = aff.world_to_pixel(wx, wy)
    assert abs(col - 20) < 1e-9 and abs(row - 20) < 1e-9
