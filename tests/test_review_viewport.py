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


def test_weighted_box_fusion_fuses_nested_containment_and_adjacent_boxes() -> None:
    from forestds.review.merge_service import weighted_box_fusion

    # 包含嵌套框：小框(30x30)完全在外部大框(50x50)内部，标准IoU只有0.36，但通过包含度/中心距离能被准确识别并融合为1个
    nested_candidates = [
        {"id": "outer", "species": "红树", "box_px": [0, 0, 50, 50], "confidence": 0.8},
        {"id": "inner", "species": "红树", "box_px": [10, 10, 40, 40], "confidence": 0.9},
    ]
    fused = weighted_box_fusion(nested_candidates)
    assert len(fused) == 1
    assert fused[0]["species"] == "红树"
    assert fused[0]["confidence"] == 0.9


def test_filter_candidates_by_existing_single_and_cumulative_coverage() -> None:
    from forestds.review.merge_service import _calculate_union_area, filter_candidates_by_existing

    # 1. 测试多矩形并集面积算法
    # 两个 10x10 的矩形，重叠 5x10，总并集面积应为 100 + 100 - 50 = 150
    b1 = (0.0, 0.0, 10.0, 10.0)
    b2 = (5.0, 0.0, 15.0, 10.0)
    assert _calculate_union_area([b1, b2]) == 150.0

    # 2. 单框覆盖测试
    existing = [
        {"id": "ex1", "species": "红树", "box_px": [0, 0, 100, 100]},
    ]
    candidates = [
        # cand1: 80% 落在 ex1 内 (0~80, 0~100) -> 面积 8000 / 10000 = 80% >= 50% -> 剔除
        {"id": "c1", "species": "红树", "box_px": [0, 0, 80, 100], "confidence": 0.9},
        # cand2: 40% 落在 ex1 内 (60~100, 0~100) -> 面积 4000 / 10000 = 40% < 50% -> 保留
        {"id": "c2", "species": "红树", "box_px": [60, 0, 160, 100], "confidence": 0.85},
        # cand3: 0% 落在 ex1 内 -> 保留
        {"id": "c3", "species": "红树", "box_px": [200, 200, 250, 250], "confidence": 0.8},
    ]
    filtered = filter_candidates_by_existing(candidates, existing, max_coverage_ratio=0.50)
    assert [c["id"] for c in filtered] == ["c2", "c3"]

    # 3. 多框拼接累积覆盖测试 (双树夹缝中的虚假候选框)
    existing_pair = [
        {"id": "tree_left", "species": "红树", "box_px": [0, 0, 50, 100]},
        {"id": "tree_right", "species": "红树", "box_px": [70, 0, 120, 100]},
    ]
    # candidate 跨在两者中间: [20, 0, 100, 100] (总宽80, 面积8000)
    # tree_left 覆盖 [20, 0, 50, 100] -> 宽30, 面积3000 (37.5%)
    # tree_right 覆盖 [70, 0, 100, 100] -> 宽30, 面积3000 (37.5%)
    # 单框均未达到 50%，但两框联合覆盖 6000 / 8000 = 75% >= 50% -> 必须剔除！
    mid_candidate = [{"id": "c_mid", "species": "红树", "box_px": [20, 0, 100, 100], "confidence": 0.7}]
    res = filter_candidates_by_existing(mid_candidate, existing_pair, max_coverage_ratio=0.50)
    assert len(res) == 0


