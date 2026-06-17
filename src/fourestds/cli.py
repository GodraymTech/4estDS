"""4estDS CLI 骨架。

根命令 ``4estds``,子命令 ``infer / preprocess / train / report / db / batch``。
设计上对应 Typer;为保证无额外依赖也能运行,这里用标准库 argparse。
本地装了 Typer 后可迫渐迁移(TODO)。
"""
from __future__ import annotations

import argparse
import sys

from . import __codename__, __version__, paths
from .config import load_settings
from .logging_setup import setup_logging


def _bootstrap():
    paths.ensure_home()
    settings = load_settings()
    logger, run_id = setup_logging(level=settings.get("logging.level", "INFO"))
    return settings, logger, run_id


def _cmd_infer(args: argparse.Namespace) -> int:
    settings, logger, run_id = _bootstrap()
    arch = args.arch or settings.get("detect.arch", "yolo12")
    logger.info(f"[infer] run_id={run_id} arch={arch} image={args.image}")
    # TODO(阶段三): 接入 BaseDetector 注册表与真实推理,产出三件套
    logger.info("[infer] TODO: 推理引擎尚未实现(阶段三)")
    return 0


def _cmd_preprocess(args: argparse.Namespace) -> int:
    settings, logger, run_id = _bootstrap()
    logger.info(f"[preprocess] run_id={run_id} tiff={args.tiff}")
    from .preprocess.slicing import plan_tiles_demo

    summary = plan_tiles_demo(settings)
    logger.info(f"[preprocess] 示例切片规划: {summary}")
    return 0


def _cmd_train(args: argparse.Namespace) -> int:
    _, logger, run_id = _bootstrap()
    logger.info(f"[train] run_id={run_id} (feature-gated)")
    logger.info("[train] TODO: 训练模块按功能授权解锁(阶段八)")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    _, logger, run_id = _bootstrap()
    logger.info(f"[report] run_id={run_id}")
    logger.info("[report] TODO: 专业统计报告(阶段六)")
    return 0


def _cmd_batch(args: argparse.Namespace) -> int:
    _, logger, run_id = _bootstrap()
    logger.warning("[batch] 仅支持 RGB;批量推理串行执行。")
    logger.info("[batch] TODO: 批量处理(阶段六)")
    return 0


def _cmd_db(args: argparse.Namespace) -> int:
    settings, logger, run_id = _bootstrap()
    from .db import schema

    if args.db_action == "init":
        path = schema.init_db()
        logger.info(f"[db] 数据库已初始化: {path}")
    elif args.db_action == "migrate":
        logger.info("[db] TODO: 接入 Alembic 迁移(现以 init 建表作为兜底)")
    else:
        logger.error("[db] 未知子命令")
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="4estds", description=f"{__codename__} CLI")
    p.add_argument("--version", action="version", version=f"{__codename__} {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    p_infer = sub.add_parser("infer", help="普通图像推理")
    p_infer.add_argument("--image", required=False, help="输入图像路径")
    p_infer.add_argument("--arch", choices=["yolo12", "rtdetr"], help="模型架构")
    p_infer.set_defaults(func=_cmd_infer)

    p_pre = sub.add_parser("preprocess", help="超大 GeoTIFF 自适应切片(创新点 A)")
    p_pre.add_argument("--tiff", required=False, help="输入 GeoTIFF 路径")
    p_pre.set_defaults(func=_cmd_preprocess)

    p_train = sub.add_parser("train", help="模型训练(feature-gated)")
    p_train.set_defaults(func=_cmd_train)

    p_report = sub.add_parser("report", help="专业统计报告")
    p_report.set_defaults(func=_cmd_report)

    p_batch = sub.add_parser("batch", help="批量处理(仅 RGB,串行)")
    p_batch.set_defaults(func=_cmd_batch)

    p_db = sub.add_parser("db", help="数据库管理")
    p_db.add_argument("db_action", choices=["init", "migrate"], help="动作")
    p_db.set_defaults(func=_cmd_db)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
