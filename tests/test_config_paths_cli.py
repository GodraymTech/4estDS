"""底座:路径/配置/CLI 烟雾测试。"""
import pytest


@pytest.fixture()
def temp_home(tmp_path, monkeypatch):
    monkeypatch.setenv("FOURESTDS_HOME", str(tmp_path / ".4estDS"))
    yield tmp_path


def test_ensure_home_creates_subdirs(temp_home):
    from fourestds import paths

    root = paths.ensure_home()
    for sub in paths.SUBDIRS:
        assert (root / sub).is_dir()
    assert paths.config_file().exists()


def test_config_layering_env_override(temp_home, monkeypatch):
    from fourestds import paths
    from fourestds.config import load_settings

    paths.ensure_home()
    monkeypatch.setenv("FOURESTDS_DETECT__ARCH", "rtdetr")
    settings = load_settings()
    assert settings.get("detect.arch") == "rtdetr"
    # overrides 优先级高于 env
    settings2 = load_settings(overrides={"detect": {"arch": "yolo12"}})
    assert settings2.get("detect.arch") == "yolo12"


def test_cli_version(capsys):
    from fourestds.cli import main

    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0


def test_cli_db_init(temp_home):
    from fourestds.cli import main

    assert main(["db", "init"]) == 0


def test_cli_preprocess_demo(temp_home):
    from fourestds.cli import main

    assert main(["preprocess"]) == 0
