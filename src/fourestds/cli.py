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


def _bootstrap(level: str | None = None):
    paths.ensure_home()
    settings = load_settings()
    logger, run_id = setup_logging(
        level=level or settings.get("logging.level", "INFO")
    )
    return settings, logger, run_id


def _demo_trees(width: int, height: int, n: int) -> list[tuple]:
    """生成确定性网格状的合成真值树(供 mock 端到端演示)。"""
    import math

    cols = max(1, int(math.sqrt(n)))
    rows = max(1, (n + cols - 1) // cols)
    trees: list[tuple] = []
    for r in range(rows):
        for c in range(cols):
            if len(trees) >= n:
                break
            cx = int((c + 0.5) / cols * width)
            cy = int((r + 0.5) / rows * height)
            trees.append((cx, cy, 40))
    return trees


def _cmd_infer(args: argparse.Namespace) -> int:
    import time

    settings, logger, run_id = _bootstrap(getattr(args, "log_level", None))
    arch = args.arch or settings.get("detect.arch", "yolo12")
    from .db import writer
    from .detect import get_detector
    from .engine import SyntheticImageSource, run_inference

    logger.info(f"[infer] run_id={run_id} arch={arch} image={args.image}")
    writer.start_run_log(
        run_id, "infer", model_arch=arch, input_path=args.image,
        params={"arch": arch, "image": args.image},
    )
    t0 = time.time()
    source = None
    try:
        if arch == "mock":
            width = int(args.width or 4096)
            height = int(args.height or 4096)
            trees = _demo_trees(width, height, int(args.demo_trees or 50))
            detector = get_detector("mock", trees=trees)
            source = SyntheticImageSource(width=width, height=height)
        else:
            if not args.image:
                logger.error("[infer] 真实推理需要 --image")
                writer.finish_run_log(run_id, "failed", error="missing --image")
                return 2
            from .engine import RasterImageSource

            detector = get_detector(
                arch,
                weights=settings.get("detect.weights", None),
                conf=float(settings.get("detect.conf_thr", 0.25)),
                iou=float(settings.get("postprocess.iou_thr", 0.55)),
                imgsz=int(settings.get("detect.model_input", 1024)),
                device=settings.get("detect.device", None),
            )
            source = RasterImageSource(args.image)

        result = run_inference(
            source, detector,
            root_size=int(settings.get("slicing.root_size", 1024)),
            min_size=int(settings.get("slicing.min_size", 256)),
            conf_thr=float(settings.get("detect.conf_thr", 0.25)),
            iou_thr=float(settings.get("postprocess.iou_thr", 0.55)),
            overlap_px=int(
                args.overlap
                if args.overlap is not None
                else settings.get("slicing.overlap_px", 0)
            ),
            conf_type=str(settings.get("postprocess.conf_type", "max")),
        )
        tract_id = writer.ensure_tract(
            args.acquisition_time or "000000",
            args.location or "demo",
            pixel_w=result.meta.get("width"),
            pixel_h=result.meta.get("height"),
        )
        written = writer.write_observations(tract_id, run_id, result.detections)
        dur = time.time() - t0
        metrics = {
            "tiles_total": result.tiles_total,
            "tiles_processed": result.tiles_processed,
            "tiles_skipped_empty": result.tiles_skipped_empty,
            "raw_count": result.raw_count,
            "fused_count": result.fused_count,
            "observations_written": written,
        }
        writer.finish_run_log(run_id, "succeeded", metrics=metrics, duration_s=dur)
        logger.info(f"[infer] 完成: {metrics}")
        return 0
    except NotImplementedError as e:
        writer.finish_run_log(
            run_id, "failed", error=str(e), duration_s=time.time() - t0
        )
        logger.warning(f"[infer] {e}")
        return 0
    except Exception as e:  # 兑底:记录失败但不崩溃
        writer.finish_run_log(
            run_id, "failed", error=str(e), duration_s=time.time() - t0
        )
        logger.exception(f"[infer] 失败: {e}")
        return 1
    finally:
        if source is not None and hasattr(source, "close"):
            source.close()


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
        logger.info("[db] TODO: 接入 Alembic 迁移(现以 init 建表作��兜底)")
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
    p_infer.add_argument("--arch", choices=["yolo12", "rtdetr", "mock"], help="模型架构")
    p_infer.add_argument("--width", type=int, help="[mock] 合成影像宽")
    p_infer.add_argument("--height", type=int, help="[mock] 合成影像高")
    p_infer.add_argument("--demo-trees", type=int, dest="demo_trees", help="[mock] 合成真值树数")
    p_infer.add_argument("--acquisition-time", dest="acquisition_time", help="地块时相 YYYYMM")
    p_infer.add_argument("--location", help="地块位置标识")
    p_infer.add_argument("--overlap", type=int, default=None, help="读窗外扩重叠像素(边界去重)")
    p_infer.add_argument(
        "--log-level", dest="log_level", default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="日志级别(默认读配置)",
    )
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
