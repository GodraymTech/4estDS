from __future__ import annotations

from pathlib import Path

from PIL import Image

from forestds.tasks.batch import build_batch_tract_id
from forestds.utils.input_inspect import (
    extract_image_phase_id,
    inspect_input_path,
    normalize_user_path,
)


def test_normalize_user_path_strips_quotes_and_converts_windows_drive() -> None:
    assert normalize_user_path('"C:\\Users\\ray\\scene.tif"') == "/mnt/c/Users/ray/scene.tif"
    assert normalize_user_path("' /tmp/scene.tif '") == "/tmp/scene.tif"


def test_inspect_input_path_file_reads_stem_and_mtime_date(tmp_path: Path) -> None:
    image = tmp_path / "Q12.tif"
    Image.new("RGB", (12, 8), color="green").save(image)

    kind, resolved, items = inspect_input_path(str(image))

    assert kind == "file"
    assert resolved == image.resolve()
    assert len(items) == 1
    assert items[0].stem == "Q12"
    assert items[0].width == 12
    assert items[0].height == 8
    assert extract_image_phase_id(image)[0]


def test_build_batch_tract_id_uses_user_value_as_prefix() -> None:
    assert build_batch_tract_id(Path("/data/Q12.tif"), None) == "Q12"
    assert build_batch_tract_id(Path("/data/Q12.tif"), "珠海_斗门") == "珠海_斗门_Q12"
    assert build_batch_tract_id(Path("/data/Q12.tif"), "珠海_斗门", 2) == "珠海_斗门_Q12_2"
