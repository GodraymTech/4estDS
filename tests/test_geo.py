"""地理仿射变换与真实面积解析单测（纯标准库 assert）。

覆盖：世界文件解析、像元面积、投影/地理坐标系米制换算、.prj 解析、
sidecar 与内嵌 GeoTIFF 标签端到端、缺失时返回 None。
"""
from __future__ import annotations

import os
import tempfile


def test_affine_from_world_file_and_pixel_area():
    from fourestds.geo import Affine
    # A,D,B,E,C,F
    aff = Affine.from_world_file(["0.5", "0.0", "0.0", "-0.5", "500000.0", "3000000.0"])
    assert aff.a == 0.5 and aff.e == -0.5
    assert abs(aff.pixel_area() - 0.25) < 1e-12
    assert abs(aff.pixel_size_x() - 0.5) < 1e-12


def test_affine_from_gdal_order():
    from fourestds.geo import Affine
    # GDAL geotransform: (c, a, b, f, d, e)
    aff = Affine.from_gdal((500000.0, 0.5, 0.0, 3000000.0, 0.0, -0.5))
    assert aff.a == 0.5 and aff.c == 500000.0 and aff.e == -0.5


def test_geoinfo_projected_area_m2():
    from fourestds.geo import Affine, GeoInfo
    aff = Affine.from_pixel_scale(0.5, 0.5)
    gi = GeoInfo(transform=aff, crs_kind="projected", linear_unit_m=1.0)
    assert abs(gi.pixel_area_m2() - 0.25) < 1e-12
    assert abs(gi.gsd_m() - 0.5) < 1e-12


def test_geoinfo_projected_feet_unit():
    from fourestds.geo import Affine, GeoInfo
    aff = Affine.from_pixel_scale(1.0, 1.0)
    gi = GeoInfo(transform=aff, crs_kind="projected", linear_unit_m=0.3048)
    # 1 ft x 1 ft = 0.3048^2 m^2
    assert abs(gi.pixel_area_m2() - 0.3048 ** 2) < 1e-9


def test_geoinfo_geographic_needs_lat():
    from fourestds.geo import Affine, GeoInfo
    aff = Affine.from_pixel_scale(0.000005, 0.000005)
    # 无纬度 -> None
    assert GeoInfo(transform=aff, crs_kind="geographic", origin_lat=None).pixel_area_m2() is None
    # 赤道处 1 度约 111320 m;像元 5e-6 度
    gi = GeoInfo(transform=aff, crs_kind="geographic", origin_lat=0.0)
    expect = (0.000005 * 111320.0) ** 2
    assert abs(gi.pixel_area_m2() - expect) < 1e-6


def test_parse_prj_projected_vs_geographic():
    from fourestds.geo import _parse_prj
    kind, unit = _parse_prj('PROJCS["UTM",GEOGCS["WGS84"],UNIT["metre",1.0]]')
    assert kind == "projected" and abs(unit - 1.0) < 1e-9
    kind2, _ = _parse_prj('GEOGCS["WGS 84",UNIT["degree",0.0174532925]]')
    assert kind2 == "geographic"


def test_compute_tract_geometry_world_file_roundtrip():
    from fourestds.geo import compute_tract_geometry
    with tempfile.TemporaryDirectory() as d:
        tif = os.path.join(d, "plot.tif")
        open(tif, "wb").write(b"\x00")  # 占位(不依赖像素,走 sidecar 路径)
        open(os.path.join(d, "plot.tfw"), "w").write(
            "0.25\n0.0\n0.0\n-0.25\n500000.0\n3000000.0\n"
        )
        open(os.path.join(d, "plot.prj"), "w").write(
            'PROJCS["UTM 50N",GEOGCS["WGS84"],UNIT["metre",1.0]]'
        )
        g = compute_tract_geometry(tif, 2048, 2048)
        assert g is not None
        assert g["crs_kind"] == "projected" and g["geo_source"] == "world_file"
        assert abs(g["gsd"] - 0.25) < 1e-9
        assert abs(g["geo_area"] - 2048 * 2048 * 0.0625) < 1e-3


def test_compute_tract_geometry_missing_returns_none():
    from fourestds.geo import compute_tract_geometry
    # 不存在的路径 + 无 transform -> None
    assert compute_tract_geometry("/no/such/file_xyz.tif", 100, 100) is None
    assert compute_tract_geometry(None, 100, 100) is None
