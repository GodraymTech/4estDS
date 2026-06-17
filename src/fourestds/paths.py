"""统一数据目录 ``~/.4estDS`` 的管理。

可用环境变量 ``FOURESTDS_HOME`` 覆盖根目录。首次访问自动初始化子目录,
并在缺失时写入一份默认 ``config.yaml``。
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

_ENV_HOME = "FOURESTDS_HOME"
_DEFAULT_DIRNAME = ".4estDS"

# 运行期子目录
SUBDIRS = ("config", "cache", "logs", "db", "outputs", "models", "tmp")


def home_dir() -> Path:
    """返回 4estDS 运行期根目录(不保证已创建)。"""
    env = os.environ.get(_ENV_HOME)
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / _DEFAULT_DIRNAME).resolve()


def ensure_home() -> Path:
    """创建根目录与全部子目录,确保默认 config.yaml 存在。返回根目录。"""
    root = home_dir()
    root.mkdir(parents=True, exist_ok=True)
    for sub in SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    cfg = config_file()
    if not cfg.exists():
        packaged = Path(__file__).resolve().parent.parent.parent / "configs" / "default.yaml"
        if packaged.exists():
            shutil.copyfile(packaged, cfg)
        else:  # pragma: no cover - 打包后兜底
            cfg.write_text("# 4estDS user config\n", encoding="utf-8")
    return root


def subdir(name: str) -> Path:
    if name not in SUBDIRS:
        raise ValueError(f"unknown subdir: {name!r}; expected one of {SUBDIRS}")
    p = home_dir() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_file() -> Path:
    return home_dir() / "config" / "config.yaml"


def logs_dir() -> Path:
    return subdir("logs")


def db_dir() -> Path:
    return subdir("db")


def outputs_dir() -> Path:
    return subdir("outputs")


def models_dir() -> Path:
    return subdir("models")


def default_db_path() -> Path:
    return db_dir() / "4estds.sqlite"
