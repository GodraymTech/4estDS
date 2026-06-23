"""统一数据目录 ``~/.4estDS`` 的管理。

可用环境变量 ``forestds_HOME`` 覆盖根目录。首次访问自动初始化子目录,
并在缺失时写入一份默认 ``config.yaml``。
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from datetime import datetime

_ENV_HOME = "forestds_HOME"
_DEFAULT_DIRNAME = ".4estDS"

# 运行期基础子目录
SUBDIRS = ("config", "cache", "logs", "db", "outputs", "models", "tmp")

# 运行时上下文变量
_current_run_id: str | None = None
_current_task_type: str | None = None
_current_date_str: str | None = None


def set_run_context(run_id: str, task_type: str | None = None) -> None:
    """设置当前运行环境的 run_id 和任务类型，用以动态定位该轮运行专属的 outputs 子目录。"""
    global _current_run_id, _current_task_type, _current_date_str
    _current_run_id = run_id
    _current_task_type = task_type
    _current_date_str = datetime.now().strftime("%Y%m%d_%H%M")


def home_dir() -> Path:
    """返回 4estDS 运行期根目录(不保证已创建)。
    如果用户通过环境变量自定义了路径，确保其尾部总是 _DEFAULT_DIRNAME。
    """
    env = os.environ.get(_ENV_HOME)
    if env:
        p = Path(env).expanduser().resolve()
        if p.name != _DEFAULT_DIRNAME:
            p = p / _DEFAULT_DIRNAME
        return p
    # TODO复原
    # return (Path.home() / _DEFAULT_DIRNAME).resolve()
    return Path(__file__).resolve().parent.parent.parent / _DEFAULT_DIRNAME


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
    # return home_dir() / "config" / "config.yaml"
    # TODO还原
    return Path("/home/ray/rays/repos/4estDS/configs/default.yaml")


def logs_dir() -> Path:
    return subdir("logs")


def db_dir() -> Path:
    return subdir("db")


def outputs_dir() -> Path:
    return subdir("outputs")


def run_dir() -> Path:
    """返回当前运行期核心输出目录: outputs/YYYYmmdd_HHMM__run_id__<infer/train/空>"""
    global _current_date_str
    if _current_date_str is None:
        _current_date_str = datetime.now().strftime("%Y%m%d_%H%M")
    run_id = _current_run_id or "default"
    task_type = _current_task_type
    if task_type:
        folder_name = f"{_current_date_str}_{run_id}_{task_type}"
    else:
        folder_name = f"{_current_date_str}_{run_id}"
    p = outputs_dir() / folder_name

    p.mkdir(parents=True, exist_ok=True)
    return p



def outputs_preprocess_dir() -> Path:
    """返回 outputs/YYYYmmdd_HHMM__run_id__<infer/train/空>/preprocess """
    p = run_dir() / "preprocess"
    p.mkdir(parents=True, exist_ok=True)
    return p


def outputs_postprocess_dir() -> Path:
    """返回 outputs/YYYYmmdd_HHMM__run_id__<infer/train/空>/postprocess """
    p = run_dir() / "postprocess"
    p.mkdir(parents=True, exist_ok=True)
    return p


def outputs_train_dir() -> Path:
    """返回 outputs/YYYYmmdd_HHMM__run_id__<infer/train/空>/train """
    p = run_dir() / "train"
    p.mkdir(parents=True, exist_ok=True)
    return p


def outputs_infer_dir() -> Path:
    # """返回 outputs/YYYYmmdd_HHMM__run_id__<infer/train/空>/infer """
    # p = run_dir() / "infer"
    # p.mkdir(parents=True, exist_ok=True)
    # return p
    return run_dir()


def models_dir() -> Path:
    return subdir("models")


def default_db_path() -> Path:
    return db_dir() / "4estds.sqlite"
