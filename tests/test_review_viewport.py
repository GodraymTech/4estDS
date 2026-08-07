from __future__ import annotations

import pytest
from affine import Affine

from forestds.review import ReviewValidationError
from forestds.review.inference_service import viewport_to_pixel_window
from forestds.review.merge_service import ReviewMergeService, non_max_suppression


def test_viewport_wgs84_maps_exactly_to_tiff_pixel_window() -> None:
    window = viewport_to_pixel_window(
        [0.2, 0.4, 0.6, 0.8],
        raster_crs="EPSG:4326",
        transform=Affine(0.01, 0, 0, 0, -0.01, 1),
        width=100,
        height=100,
    )
    assert window == (20, 20, 40, 40)


def test_viewport_outside_tiff_is_rejected() -> None:
    with pytest.raises(ReviewValidationError) as failure:
        viewport_to_pixel_window(
            [2, 2, 3, 3], raster_crs="EPSG:4326", transform=Affine(0.01, 0, 0, 0, -0.01, 1), width=100, height=100
        )
    assert failure.value.code == "viewport_outside_tiff"


def test_replace_all_discards_previous_workspace() -> None:
    parent = {"id": "parent", "source": "parent", "confirmed": True, "species": "A", "box_px": [10, 10, 20, 20]}
    human = {"id": "human", "source": "human", "confirmed": True, "species": "A", "box_px": [30, 30, 40, 40]}
    candidate = {"id": "new", "source": "ai", "confirmed": False, "species": "B", "box_px": [52, 52, 62, 62], "confidence": 0.9}

    result = ReviewMergeService().apply("replace_all", [parent, human], [candidate])

    assert {item["id"] for item in result} == {"new"}
    assert all(item["frozen"] is False for item in result)


def test_append_freezes_existing_and_drops_duplicate_candidates() -> None:
    existing = [
        {"id": "kept", "source": "ai", "confirmed": False, "species": "B", "box_px": [50, 50, 60, 60]},
    ]
    duplicate = {"id": "dup", "source": "ai", "species": "B", "box_px": [50.5, 50.5, 60.5, 60.5], "confidence": 0.9}
    fresh = {"id": "fresh", "source": "ai", "species": "B", "box_px": [80, 80, 90, 90], "confidence": 0.9}
    # 同位置但属不同树种，去重按类别隔离，不应被丢弃。
    other_species = {"id": "other", "source": "ai", "species": "C", "box_px": [50.5, 50.5, 60.5, 60.5], "confidence": 0.9}

    result = ReviewMergeService().apply("append", existing, [duplicate, fresh, other_species])
    by_id = {item["id"]: item for item in result}

    assert set(by_id) == {"kept", "fresh", "other"}
    assert by_id["kept"]["frozen"] is True
    assert by_id["fresh"]["frozen"] is False
    assert by_id["other"]["frozen"] is False


def test_unknown_merge_mode_is_rejected() -> None:
    with pytest.raises(ValueError):
        ReviewMergeService().apply("replace_ai_in_scope", [], [])


def test_candidate_nms_is_category_aware() -> None:
    candidates = [
        {"id": "a", "species": "A", "box_px": [0, 0, 10, 10], "confidence": 0.9},
        {"id": "b", "species": "A", "box_px": [1, 1, 11, 11], "confidence": 0.5},
        {"id": "c", "species": "B", "box_px": [1, 1, 11, 11], "confidence": 0.4},
    ]
    assert [item["id"] for item in non_max_suppression(candidates, 0.6)] == ["a", "c"]
