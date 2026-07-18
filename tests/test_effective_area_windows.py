from __future__ import annotations

import json
import sqlite3

import numpy as np
import pytest
from affine import Affine
from shapely.geometry import box, mapping

from forestds.db import schema
from forestds.detect.base import BaseDetector, Detection, Detections, Window
from forestds.effective_area.windows import (
    EffectiveWindowCache,
    EffectiveWindowFilter,
    effective_window_cache_key,
    load_effective_window_filter,
)
from forestds.engine.infer import InferenceConfig, run_inference

def test_windows_classify_inside_outside_and_boundary() -> None:
    filter_ = EffectiveWindowFilter.from_pixel_geometry(box(0, 0, 100, 100))

    assert filter_.classify((10, 10, 20, 20)) == "inside"
    assert filter_.classify((110, 10, 20, 20)) == "outside"
    assert filter_.classify((90, 10, 20, 20)) == "boundary"
    # 仅与边界线接触但没有面积重叠，不应进入模型。
    assert filter_.classify((100, 10, 20, 20)) == "outside"


def test_local_mask_exists_only_for_boundary_windows() -> None:
    filter_ = EffectiveWindowFilter.from_pixel_geometry(box(10, 10, 90, 90))
    inside = Window(20, 20, 20, 20)
    outside = Window(110, 0, 20, 20)
    boundary = Window(0, 0, 100, 100)

    assert filter_.local_mask(inside) is None
    assert filter_.local_mask(outside) is None
    mask = filter_.local_mask(boundary)
    assert mask is not None
    assert mask.shape == (100, 100)
    assert mask.dtype == np.bool_
    assert bool(mask[50, 50]) is True
    assert bool(mask[0, 0]) is False
    assert not hasattr(filter_, "full_image_mask")


def test_keep_detection_uses_center_point_and_includes_boundary() -> None:
    filter_ = EffectiveWindowFilter.from_pixel_geometry(box(10, 10, 90, 90))

    assert filter_.keep_detection((50, 50)) is True
    assert filter_.keep_detection((10, 50)) is True
    assert filter_.keep_detection((9.999, 50)) is False


def test_world_geometry_is_transformed_once_to_tiff_pixels() -> None:
    transform = Affine(0.001, 0, 113.0, 0, -0.001, 22.1)
    world = box(113.01, 22.01, 113.09, 22.09)

    filter_ = EffectiveWindowFilter.from_world_geometry(
        mapping(world),
        raster_crs="EPSG:4326",
        geotransform=transform,
        tract_pk="tract-1",
        tract_updated_at="2026-07-18T00:00:00+00:00",
        tiff_id="tif01",
    )

    assert filter_.classify((20, 20, 20, 20)) == "inside"
    assert filter_.classify((0, 0, 5, 5)) == "outside"


def test_cache_key_contains_every_spatial_version_component() -> None:
    transform = Affine(1, 0, 0, 0, -1, 100)
    key = effective_window_cache_key("tract-1", "updated-1", "tif01", transform)

    assert key == ("tract-1", "updated-1", "tif01", tuple(transform))
    assert key != effective_window_cache_key("tract-1", "updated-2", "tif01", transform)
    assert key != effective_window_cache_key("tract-1", "updated-1", "tif02", transform)


def test_window_cache_is_lru_and_bounded() -> None:
    cache = EffectiveWindowCache(max_size=2)
    created: list[str] = []

    def factory(value: str) -> EffectiveWindowFilter:
        created.append(value)
        return EffectiveWindowFilter.from_pixel_geometry(box(0, 0, 10, 10))

    first = cache.get_or_create(("tract", "u1", "t1", (1, 0, 0, 0, 1, 0)), lambda: factory("first"))
    assert cache.get_or_create(("tract", "u1", "t1", (1, 0, 0, 0, 1, 0)), lambda: factory("duplicate")) is first
    cache.get_or_create(("tract", "u2", "t1", (1, 0, 0, 0, 1, 0)), lambda: factory("second"))
    cache.get_or_create(("tract", "u3", "t1", (1, 0, 0, 0, 1, 0)), lambda: factory("third"))

    assert created == ["first", "second", "third"]
    assert len(cache) == 2


def test_load_filter_uses_current_tract_version_and_tiff_transform(tmp_path) -> None:
    db_file = tmp_path / "window-cache.db"
    db_url = f"sqlite:///{db_file}"
    schema.init_db(db_url)
    transform = Affine(0.001, 0, 113.0, 0, -0.001, 22.1)
    boundary = box(113.0, 22.0, 113.1, 22.1)
    effective = box(113.01, 22.01, 113.09, 22.09)
    conn = sqlite3.connect(db_file)
    conn.execute(
        "INSERT INTO tracts "
        "(tract_pk, region_id, tract_id, boundary_geom, effective_geom, effective_area_hm2, "
        "boundary_source, coverage_status, created_at, updated_at) "
        "VALUES ('tract-1', 'region', 'Q12', ?, ?, 1, 'manual', 'full', 'created', 'updated-1')",
        (boundary.wkt, effective.wkt),
    )
    conn.execute(
        "INSERT INTO tract_phases (tract_phase_pk, tract_pk, region_id, tract_id, phase_id, updated_at) "
        "VALUES ('phase-1', 'tract-1', 'region', 'Q12', '20260718', 'updated-1')"
    )
    conn.execute(
        "INSERT INTO tiffs "
        "(tiff_id, phase_id, tract_phase_pk, footprint_geom, crs_epsg, geotransform, created_at, updated_at) "
        "VALUES ('tif01', '20260718', 'phase-1', ?, 4326, ?, 'created', 'updated')",
        (boundary.wkt, json.dumps(tuple(transform))),
    )
    conn.commit()
    conn.close()

    first = load_effective_window_filter(
        db_url=db_url,
        tract_ref="Q12",
        phase_id="20260718",
        tiff_id="tif01",
        raster_crs="EPSG:4326",
        geotransform=transform,
        cache_size=2,
    )
    second = load_effective_window_filter(
        db_url=db_url,
        tract_ref="Q12",
        phase_id="20260718",
        tiff_id="tif01",
        raster_crs="EPSG:4326",
        geotransform=transform,
        cache_size=2,
    )

    assert first is not None
    assert first is second
    assert first.classify((20, 20, 20, 20)) == "inside"
    assert first.classify((0, 0, 5, 5)) == "outside"
    assert first.cache_key[0:3] == ("tract-1", "updated-1", "tif01")

    conn = sqlite3.connect(db_file)
    conn.execute("UPDATE tracts SET updated_at='updated-2' WHERE tract_pk='tract-1'")
    conn.commit()
    conn.close()
    refreshed = load_effective_window_filter(
        db_url=db_url,
        tract_ref="Q12",
        phase_id="20260718",
        tiff_id="tif01",
        raster_crs="EPSG:4326",
        geotransform=transform,
        cache_size=2,
    )
    assert refreshed is not first
    assert refreshed.cache_key[1] == "updated-2"


def test_load_filter_returns_none_for_new_or_unreferenced_tract(tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path / 'empty.db'}"
    schema.init_db(db_url)

    assert load_effective_window_filter(
        db_url=db_url,
        tract_ref="missing",
        phase_id="20260718",
        tiff_id="tif01",
        raster_crs="EPSG:4326",
        geotransform=Affine.identity(),
    ) is None


class CountingSource:
    width = 200
    height = 100

    def __init__(self) -> None:
        self.reads: list[tuple[int, int, int, int]] = []

    def read_window(self, x: int, y: int, w: int, h: int) -> np.ndarray:
        self.reads.append((x, y, w, h))
        return np.ones((h, w, 3), dtype=np.uint8)

    def close(self) -> None:
        pass


class CenterDetector(BaseDetector):
    name = "center"

    def load(self) -> None:
        self._loaded = True

    def predict(self, window: Window) -> Detections:
        return Detections([Detection(40, 40, 60, 60, 0.9, "tree")])


def test_inference_skips_outside_windows_before_reading_pixels() -> None:
    source = CountingSource()
    filter_ = EffectiveWindowFilter.from_pixel_geometry(box(0, 0, 100, 100))

    result = run_inference(
        source,
        CenterDetector(),
        InferenceConfig(root_size=100, min_size=100, batch_size=8, overlap_rate=0, conf_thr=0.1),
        window_filter=filter_,
    )

    assert result.tiles_total == 2
    assert result.tiles_processed == 1
    assert result.tiles_skipped_empty == 1
    assert source.reads == [(0, 0, 100, 100)]
    assert len(result.detections) == 1


class MaskDetector(BaseDetector):
    name = "mask"

    def __init__(self) -> None:
        super().__init__()
        self.saw_local_mask = False

    def load(self) -> None:
        self._loaded = True

    def predict(self, window: Window) -> Detections:
        pixels = np.asarray(window.pixels)
        self.saw_local_mask = bool(np.all(pixels[:, 60:, :] == 0) and np.any(pixels[:, :40, :] != 0))
        return Detections(
            [
                Detection(20, 40, 30, 60, 0.9, "inside"),
                Detection(70, 40, 80, 60, 0.9, "outside"),
            ]
        )


def test_boundary_window_uses_local_mask_and_center_filters_detections() -> None:
    source = CountingSource()
    source.width = 100
    detector = MaskDetector()
    filter_ = EffectiveWindowFilter.from_pixel_geometry(box(0, 0, 50, 100))

    result = run_inference(
        source,
        detector,
        InferenceConfig(root_size=100, min_size=100, batch_size=1, overlap_rate=0, conf_thr=0.1),
        window_filter=filter_,
    )

    assert detector.saw_local_mask is True
    assert [item.label for item in result.detections] == ["inside"]
    assert result.raw_count == 1
