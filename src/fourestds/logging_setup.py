"""工业级统一日志。

设计要点：
- **单一规范通道**：所有模块用 ``get_logger(__name__)`` 取 logger，均挂在
  ``fourestds`` 根 logger 下，统一继承 handler / level / run_id。
- **控制台 + 滚动文件**：RotatingFileHandler（20MB × 5），日志落在 ``~/.4estDS/logs``。
- **run_id 贯穿全链路**：通过 Filter 注入每条记录，子 logger 自动携带，
  便于把一次运行的所有日志串起来查。
- **可选 loguru**：装了 loguru 则用 InterceptHandler 把标准库日志转发进 loguru
  （同时拥有 loguru 的控制台高亮与滚动 sink）；未装则纯标准库，零额外依赖也能跑。
- **分布可观测**：``summarize_distribution`` / ``log_distribution`` 一行打印
  计数/min/max/均值/中位/分位，专门服务“目标尺寸分布估计、离散尺度集”等需求。
"""
from __future__ import annotations

import logging
import math
import uuid
from logging.handlers import RotatingFileHandler

from . import paths

ROOT_LOGGER_NAME = "fourestds"
_CONSOLE_FMT = "%(asctime)s | %(levelname)-7s | run=%(run_id)s | %(name)s | %(message)s"

# 当前 run_id（被 _RunIdFilter 注入到每条记录）。
_CURRENT_RUN_ID = "-"


class _RunIdFilter(logging.Filter):
    """为每条记录注入 run_id（若调用方未显式提供）。"""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if not hasattr(record, "run_id"):
            record.run_id = _CURRENT_RUN_ID
        return True


def new_run_id() -> str:
    """生成一个短 run_id（全链路关联用）。"""
    return uuid.uuid4().hex[:12]


def current_run_id() -> str:
    """返回当前 run_id。"""
    return _CURRENT_RUN_ID


def get_logger(name: str | None = None) -> logging.Logger:
    """模块内统一取 logger：``log = get_logger(__name__)``。

    始终挂在 ``fourestds`` 根 logger 下，以继承其 handler / level / run_id。
    传入包内模块名（如 ``fourestds.preprocess.slicing``）则原样返回该子 logger；
    传入其它名字则挂到根下的同名叶节点。
    """
    if not name or name == ROOT_LOGGER_NAME:
        return logging.getLogger(ROOT_LOGGER_NAME)
    if name.startswith(ROOT_LOGGER_NAME + "."):
        return logging.getLogger(name)
    leaf = name.split(".")[-1]
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{leaf}")


def _install_loguru(level: str, to_file: bool) -> bool:
    """若 loguru 可用，配置 sink 并用 InterceptHandler 把标准库日志转发进去。"""
    try:
        from loguru import logger as _loguru_logger  # type: ignore
    except Exception:  # noqa: BLE001 - loguru 未装则回退
        return False

    import sys

    fmt = (
        "{time:YYYY-MM-DD HH:mm:ss} | {level: <7} | "
        "run={extra[run_id]} | {name} | {message}"
    )
    _loguru_logger.remove()
    _loguru_logger.configure(extra={"run_id": _CURRENT_RUN_ID})
    _loguru_logger.add(sys.stderr, level=level, format=fmt, enqueue=True)
    if to_file:
        log_path = paths.logs_dir() / f"4estds_{_CURRENT_RUN_ID}.log"
        _loguru_logger.add(
            str(log_path), level=level, format=fmt,
            rotation="20 MB", retention=5, enqueue=True,
        )

    class InterceptHandler(logging.Handler):
        """标准库 -> loguru 转发（loguru 官方推荐写法）。"""

        def emit(self, record: logging.LogRecord) -> None:
            try:
                lvl = _loguru_logger.level(record.levelname).name
            except (ValueError, AttributeError):
                lvl = record.levelno
            frame, depth = logging.currentframe(), 2
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1
            run_id = getattr(record, "run_id", _CURRENT_RUN_ID)
            _loguru_logger.bind(run_id=run_id).opt(
                depth=depth, exception=record.exc_info
            ).log(lvl, record.getMessage())

    root = logging.getLogger(ROOT_LOGGER_NAME)
    root.handlers.clear()
    root.addHandler(InterceptHandler())
    return True


def setup_logging(level: str = "INFO", run_id: str | None = None, to_file: bool = True):
    """配置日志。幂等：重复调用会重建 handler。返回 (logger, run_id)。"""
    global _CURRENT_RUN_ID
    run_id = run_id or new_run_id()
    _CURRENT_RUN_ID = run_id

    root = logging.getLogger(ROOT_LOGGER_NAME)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    for flt in list(root.filters):
        root.removeFilter(flt)
    root.addFilter(_RunIdFilter())
    root.propagate = False

    if _install_loguru(level, to_file):
        root.debug("loguru logging initialised")
        return root, run_id

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_CONSOLE_FMT))
    console.addFilter(_RunIdFilter())
    root.addHandler(console)

    if to_file:
        log_path = paths.logs_dir() / f"4estds_{run_id}.log"
        fh = RotatingFileHandler(
            log_path, maxBytes=20 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        fh.setFormatter(logging.Formatter(_CONSOLE_FMT))
        fh.addFilter(_RunIdFilter())
        root.addHandler(fh)

    root.debug("stdlib logging initialised (loguru not available)")
    return root, run_id


# --------------------------------------------------------------------------- #
# 分布可观测工具（尺寸分布 / 离散尺度集等）
# --------------------------------------------------------------------------- #


def summarize_distribution(values) -> dict:
    """返回数值分布摘要 dict：n/min/max/mean/median/p10/p90/std。

    纯标准库实现（不依赖 numpy），空输入返回 {"n": 0}。
    """
    xs = sorted(float(v) for v in values if v is not None)
    n = len(xs)
    if n == 0:
        return {"n": 0}
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / n

    def pct(p: float) -> float:
        if n == 1:
            return xs[0]
        idx = p / 100.0 * (n - 1)
        lo = int(math.floor(idx))
        hi = int(math.ceil(idx))
        if lo == hi:
            return xs[lo]
        frac = idx - lo
        return xs[lo] * (1 - frac) + xs[hi] * frac

    return {
        "n": n,
        "min": xs[0],
        "max": xs[-1],
        "mean": mean,
        "median": pct(50),
        "p10": pct(10),
        "p90": pct(90),
        "std": math.sqrt(var),
    }


def format_distribution(values, *, unit: str = "") -> str:
    """把分布摘要格式化为一行可读字符串。"""
    s = summarize_distribution(values)
    if s["n"] == 0:
        return "n=0 (空)"
    u = unit
    return (
        f"n={s['n']} min={s['min']:.1f}{u} p10={s['p10']:.1f}{u} "
        f"median={s['median']:.1f}{u} mean={s['mean']:.1f}{u} "
        f"p90={s['p90']:.1f}{u} max={s['max']:.1f}{u} std={s['std']:.1f}{u}"
    )


def log_distribution(log, label: str, values, *, unit: str = "", level: int = logging.INFO) -> dict:
    """打印并返回分布摘要。供“尺寸分布估计”等场景一行观测。"""
    summary = summarize_distribution(values)
    log.log(level, "%s 分布: %s", label, format_distribution(values, unit=unit))
    return summary
