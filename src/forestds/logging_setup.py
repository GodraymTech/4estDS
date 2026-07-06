"""工业级统一日志。

设计要点：
- **单一规范通道**：所有模块用 ``get_logger(__name__)`` 取 logger，均挂在
  ``forestds`` 根 logger 下，统一继承 handler / level / run_id。
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
import sys
import uuid
from loguru import logger as _loguru_logger

from . import paths

# 当前 run_id
_CURRENT_RUN_ID = "-"

# 统一的启动时间戳，确保长时运行(如训练多小时)期间日志文件名固定，绝不因分钟变化发生分裂
import datetime as _datetime
_LAUNCH_TIME = _datetime.datetime.now().strftime("%Y%m%d_%H%M")



# 允许放行的第三方依赖日志白名单及其对应的最低显示级别（默认只放行 forestds 和 __main__）
# 未在此列表中的第三方依赖，仅在其日志级别 >= WARNING 时放行
DEPENDENCY_LOG_WHITELIST = {
    "ultralytics": "INFO"
}


def new_run_id() -> str:
    """生成一个短 run_id（全链路关联用）。"""
    return uuid.uuid4().hex[:5]


def current_run_id() -> str:
    """返回当前 run_id。"""
    return _CURRENT_RUN_ID


def setup_logging(
    level: str = "INFO",
    run_id: str | None = None,
    to_file: bool = True,
    task_type: str | None = None,
    raw_file: bool = False,
):
    """配置 loguru 日志，并拦截标准库日志。返回 (logger, run_id)。"""
    global _CURRENT_RUN_ID
    run_id = run_id or new_run_id()
    _CURRENT_RUN_ID = run_id

    def _formatter(record) -> str:
        import os
        try:
            # 自动计算相对于当前工作区根目录的物理相对路径，实现 VS Code/Cursor 终端中 Cmd/Ctrl+Click 的完美超链接跳转
            rel_path = os.path.relpath(record["file"].path)
        except Exception:
            rel_path = record["file"].name
        
        exc_part = "{exception}" if record["exception"] else ""
        return (
            f"<green>{{time:YYYY-MM-DD HH:mm:ss}}</green> | "
            f"<level>{{level: <4}}</level> | "
            f"<cyan>{{extra[run_id]}}</cyan> | "
            f"<cyan>{rel_path}:{{line}}</cyan> | "
            f"<level>{{message}}</level>\n{exc_part}"
        )

    def _filter(record) -> bool:
        name = record["extra"].get("logger_name", record["name"])
        # 0. 过滤 ultralytics 推理的每张图检测详情与空行
        if name.startswith("ultralytics"):
            msg = record["message"]
            import re
            if re.match(r"^\d+:\s+\d+x\d+", msg):
                return False
            if not msg.strip():
                return False
        # 1. 本项目和主入口，全部放行
        if name.startswith("forestds") or name == "__main__":
            return True
        # 2. 对白名单中的依赖包，根据对应的最小日志等级放行
        for wl_name, min_level in DEPENDENCY_LOG_WHITELIST.items():
            if name.startswith(wl_name):
                try:
                    record_level_no = record["level"].no
                    wl_level_no = _loguru_logger.level(min_level).no
                    if record_level_no >= wl_level_no:
                        return True
                except Exception:
                    pass
        # 3. 任何非白名单中的其他依赖，如果是 WARNING 或以上级别，也放行以防静默报错
        if record["level"].no >= 30:  # WARNING 级别是 30
            return True
        return False

    from tqdm import tqdm
    _loguru_logger.remove()
    _loguru_logger.configure(extra={"run_id": _CURRENT_RUN_ID})
    _loguru_logger.add(
        lambda msg: tqdm.write(msg, end=""),
        level=level, format=_formatter, filter=_filter, enqueue=True, colorize=True
    )
    if to_file:
        log_filename = f"{_LAUNCH_TIME}__{_CURRENT_RUN_ID}__{task_type}.log"
        log_path = paths.logs_dir() / log_filename
        _loguru_logger.add(
            str(log_path), level=level, format=_formatter,
            filter=_filter, rotation="20 MB", retention=5, enqueue=True,
        )
        # 前端日志展示直接读取主日志并实时清洗 formatter 前缀，不再额外落 .ui.log。
        # raw_file 参数保留为兼容旧调用。


    class InterceptHandler(logging.Handler):
        """标准库 -> loguru 转发（loguru 官方推荐写法）。"""

        def emit(self, record: logging.LogRecord) -> None:
            try:
                lvl = _loguru_logger.level(record.levelname).name
            except (ValueError, AttributeError):
                lvl = record.levelno

            # Find caller from where originated the logged message
            frame, depth = logging.currentframe(), 0
            import os
            logging_dir = os.path.dirname(logging.__file__)
            while frame and (
                frame.f_code.co_filename == logging.__file__
                or frame.f_code.co_filename.startswith(logging_dir)
                or "logging_setup" in frame.f_code.co_filename
                or "frozen logging" in frame.f_code.co_filename
            ):
                frame = frame.f_back
                depth += 1

            run_id = getattr(record, "run_id", _CURRENT_RUN_ID)
            _loguru_logger.bind(run_id=run_id, logger_name=record.name).opt(
                depth=depth, exception=record.exc_info
            ).log(lvl, record.getMessage())

    # 全局重定向标准 library logging 到 loguru InterceptHandler
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # 显式重置并打通 ultralytics 日志通道，使之能向上传播到根日志器，被 InterceptHandler 拦截并写入日志文件
    ultra_log = logging.getLogger("ultralytics")
    ultra_log.propagate = True
    ultra_log.handlers = []

    # 显式限制第三方高噪声依赖的日志等级，避免其底层 C/C++ 库 (如 GDAL) 的 DEBUG 日志倾泻
    # 注意：为了让 Ultralytics 的训练指标和进度打印能够输出到日志文件，这里将其从列表中移除，并在 DEPENDENCY_LOG_WHITELIST 中专门放行 INFO 级
    for noise_logger in ("rasterio", "gdal", "fiona", "shapely", "PIL", "matplotlib", "urllib3"):
        logging.getLogger(noise_logger).setLevel(logging.WARNING)

    _loguru_logger.debug("loguru logging initialised")
    return _loguru_logger, _CURRENT_RUN_ID


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


def log_distribution(log, label: str, values, *, unit: str = "", level: str | int = "INFO") -> dict:
    """打印并返回分布摘要。供“尺寸分布估计”等场景一行观测。"""
    summary = summarize_distribution(values)
    log.log(level, "{} 分布: {}", label, format_distribution(values, unit=unit))
    return summary
