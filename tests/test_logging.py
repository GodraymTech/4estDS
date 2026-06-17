"""日志系统单测（纯标准库 assert，不依赖 pytest fixtures）。

覆盖：
- summarize_distribution 的统计正确性与空输入。
- get_logger 的命名收敛到 fourestds 根下。
- setup_logging 后 run_id 贯穿到各模块日志。
- 阶段四 / 阶段三 关键路径会实际输出日志。
"""
from __future__ import annotations

import io
import logging

from fourestds.logging_setup import (
    ROOT_LOGGER_NAME,
    _RunIdFilter,
    format_distribution,
    get_logger,
    setup_logging,
    summarize_distribution,
)


def test_summarize_distribution_basic():
    s = summarize_distribution([10, 20, 30, 40, 50])
    assert s["n"] == 5
    assert s["min"] == 10 and s["max"] == 50
    assert s["median"] == 30
    assert abs(s["mean"] - 30) < 1e-9
    assert s["p10"] == 14 and s["p90"] == 46


def test_summarize_distribution_empty():
    assert summarize_distribution([])["n"] == 0
    assert summarize_distribution([None, None])["n"] == 0
    assert "空" in format_distribution([])


def test_get_logger_namespacing():
    assert get_logger().name == ROOT_LOGGER_NAME
    assert get_logger("fourestds.preprocess.slicing").name == "fourestds.preprocess.slicing"
    # 非 fourestds 前缀也收敛到根下
    assert get_logger("some.third_party").name == "fourestds.third_party"


def test_run_id_propagates_to_child_loggers():
    logger, run_id = setup_logging(level="DEBUG", to_file=False)
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(logging.Formatter("run=%(run_id)s|%(name)s|%(message)s"))
    h.addFilter(_RunIdFilter())
    logging.getLogger(ROOT_LOGGER_NAME).addHandler(h)
    try:
        get_logger("fourestds.preprocess.slicing").info("hello")
        out = buf.getvalue()
    finally:
        logging.getLogger(ROOT_LOGGER_NAME).removeHandler(h)
    assert f"run={run_id}" in out
    assert "fourestds.preprocess.slicing" in out
    assert len(run_id) == 12


def test_stage4_and_stage3_emit_logs():
    from fourestds.detect import get_detector
    from fourestds.engine.runner import SyntheticImageSource, run_inference
    from fourestds.preprocess.slicing import build_quadtree, cluster_scales

    setup_logging(level="DEBUG", to_file=False)
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(logging.Formatter("%(name)s|%(message)s"))
    h.addFilter(_RunIdFilter())
    logging.getLogger(ROOT_LOGGER_NAME).addHandler(h)
    try:
        cluster_scales([8, 9, 10, 40, 42, 45, 120, 130], k=3)
        size_map = lambda cx, cy: 512 if cx < 2048 else 1024  # noqa: E731
        build_quadtree(4096, 4096, size_map, 1024, 256)
        det = get_detector("mock", trees=[(500, 500, 40), (2600, 2600, 30)])
        run_inference(
            SyntheticImageSource(4096, 4096), det,
            target_size_fn=size_map, root_size=1024, min_size=256,
        )
        out = buf.getvalue()
    finally:
        logging.getLogger(ROOT_LOGGER_NAME).removeHandler(h)
    for key in [
        "冠幅像素尺寸 分布",
        "离散尺度集",
        "四叉树切片",
        "切片边长 分布",
        "推理开始",
        "切片清单",
        "推理完成",
    ]:
        assert key in out, f"missing log: {key}"
