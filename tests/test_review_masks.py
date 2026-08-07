from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest
from affine import Affine
from shapely.wkt import loads as load_wkt

from forestds.review import ReviewPublishService, ReviewSessionService, ReviewValidationError
from forestds.review.masks import (
    apply_brush,
    decode_mask,
    encode_mask,
    mask_item_fields,
    mask_to_tiff_geometry,
)
from test_review_sessions import PHASE, TIFF, review_db


def test_mask_rle_roundtrip() -> None:
    mask = np.array([[False, True, True], [True, False, True]], dtype=bool)
    assert np.array_equal(decode_mask(encode_mask(mask)), mask)


def test_window_mask_maps_to_tiff_pixels_and_geography() -> None:
    mask = np.zeros((4, 4), dtype=bool)
    mask[1:3, 1:3] = True
    result = mask_to_tiff_geometry(mask, [10, 20, 40, 20], Affine(2, 0, 100, 0, -3, 200))

    assert result.pixel_bounds == pytest.approx((20, 25, 40, 35))
    assert result.geometry.bounds == pytest.approx((140, 95, 180, 125))
    assert result.geometry.is_valid


def test_brush_add_erase_and_empty_mask_rejection() -> None:
    empty = encode_mask(np.zeros((10, 10), dtype=bool))
    added = apply_brush(empty, [100, 200, 20, 20], [{"mode": "add", "x": 110, "y": 210, "radius": 3}])
    assert added.any()
    erased = apply_brush(encode_mask(added), [100, 200, 20, 20], [{"mode": "erase", "x": 110, "y": 210, "radius": 20}])
    assert not erased.any()
    with pytest.raises(ReviewValidationError, match="不能为空"):
        mask_to_tiff_geometry(erased, [100, 200, 20, 20], Affine.identity())


def _add_mask_item(service: ReviewSessionService, session_id: str) -> tuple[str, int]:
    mask = np.zeros((10, 10), dtype=bool)
    mask[2:6, 2:6] = True
    fields = mask_item_fields(mask, [10, 10, 20, 20], Affine(0.01, 0, 0, 0, -0.01, 1))
    patch = service.apply_operations(
        session_id,
        0,
        "add-mask",
        [{"type": "add", "item": {"id": "mask-1", "species": "红树", **fields}}],
    )
    return "mask-1", patch.revision


def test_mask_edit_updates_geometry_and_participates_in_undo(
    review_db: tuple[str, Path],
) -> None:
    url, drafts = review_db
    service = ReviewSessionService(url, draft_root=drafts)
    session = service.create(PHASE, TIFF, "fresh")
    item_id, revision = _add_mask_item(service, session.session_id)

    edited = service.apply_mask_operation(
        session.session_id,
        revision,
        "brush-1",
        item_id,
        [{"mode": "add", "x": 27, "y": 27, "radius": 2}],
    )
    item = edited.items[0]
    assert item["mask_rle"]
    assert item["mask_geometry_px"]["type"] == "MultiPolygon"
    assert item["box_px"][2] > 25
    assert load_wkt(item["crown_geom"]).is_valid

    undone = service.undo(session.session_id, edited.revision, "undo-mask")
    assert undone.items[0]["box_px"][2] == pytest.approx(22)


def test_publish_persists_edited_mask_crown_geometry(
    review_db: tuple[str, Path],
) -> None:
    url, drafts = review_db
    service = ReviewSessionService(url, draft_root=drafts)
    session = service.create(PHASE, TIFF, "fresh")
    item_id, revision = _add_mask_item(service, session.session_id)
    edited = service.apply_mask_operation(
        session.session_id,
        revision,
        "brush-publish",
        item_id,
        [{"mode": "add", "x": 27, "y": 27, "radius": 2}],
    )
    expected = edited.items[0]["crown_geom"]

    result = ReviewPublishService(url, session_service=service).publish(session.session_id)
    conn = sqlite3.connect(url.split("///", 1)[1])
    try:
        row = conn.execute(
            "SELECT crown_geom, box_px FROM tree_observations WHERE run_id=?",
            (result["run_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == expected
    assert load_wkt(row[0]).is_valid
