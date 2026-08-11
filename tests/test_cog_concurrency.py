from pathlib import Path
import pytest
from fastapi import HTTPException
from forestds.api.routers.assets import AssetCogConvertRequest, convert_asset_cog, _active_cog_locks
from forestds.utils.atomic_io import atomic_write_json, atomic_write_text


def test_atomic_write_utilities(tmp_path: Path):
    target = tmp_path / "test_data.json"
    data = {"name": "test_atomic", "value": 123}

    result_path = atomic_write_json(target, data)
    assert result_path.exists()
    assert target.read_text(encoding="utf-8") == '{"name":"test_atomic","value":123}'

    text_target = tmp_path / "test.txt"
    atomic_write_text(text_target, "hello world")
    assert text_target.read_text(encoding="utf-8") == "hello world"


def test_cog_conversion_lock_prevents_concurrent_trigger(tmp_path: Path):
    tif_file = tmp_path / "test.tif"
    tif_file.write_bytes(b"dummy tiff content")

    resolved_path = str(tif_file.resolve())
    _active_cog_locks.add(resolved_path)

    try:
        with pytest.raises(HTTPException) as exc_info:
            convert_asset_cog(AssetCogConvertRequest(input_path=str(tif_file)))
        assert exc_info.value.status_code == 409
        assert "正在转码中" in exc_info.value.detail
    finally:
        _active_cog_locks.discard(resolved_path)
