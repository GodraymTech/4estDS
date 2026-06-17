"""日志初始化。

优先使用 ``loguru``(控制台 + 滚动文件);若未安装则回退到标准库 ``logging``
的 RotatingFileHandler,保证无额外依赖也能运行。``run_id`` 贯穿全链路。
"""
from __future__ import annotations

import logging
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import paths

_CONSOLE_FMT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def new_run_id() -> str:
    """生成一个短 run_id(全链路关联用)。"""
    return uuid.uuid4().hex[:12]


def setup_logging(level: str = "INFO", run_id: str | None = None, to_file: bool = True):
    """配置日志。返回 (logger, run_id)。"""
    run_id = run_id or new_run_id()
    log_path = paths.logs_dir() / f"4estds_{run_id}.log" if to_file else None

    try:
        from loguru import logger as _loguru_logger  # type: ignore

        _loguru_logger.remove()
        import sys

        _loguru_logger.add(sys.stderr, level=level)
        if log_path is not None:
            _loguru_logger.add(str(log_path), level=level, rotation="20 MB", retention=5)
        bound = _loguru_logger.bind(run_id=run_id)
        bound.debug("loguru logging initialised")
        return bound, run_id
    except Exception:  # noqa: BLE001 - loguru 不可用则回退
        pass

    logger = logging.getLogger("fourestds")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_CONSOLE_FMT))
    logger.addHandler(console)

    if log_path is not None:
        fh = RotatingFileHandler(log_path, maxBytes=20 * 1024 * 1024, backupCount=5)
        fh.setFormatter(logging.Formatter(_CONSOLE_FMT))
        logger.addHandler(fh)

    logger = logging.LoggerAdapter(logger, {"run_id": run_id})  # type: ignore[assignment]
    logger.debug("stdlib logging initialised (loguru not available)")
    return logger, run_id
