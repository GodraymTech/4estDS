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
        from .geo import compute_tract_geometry

        geo = compute_tract_geometry(
            args.image,
            result.meta.get("width"), result.meta.get("height"),
            transform=getattr(source, "transform", None),
            crs=getattr(source, "crs", None),
        ) or {}
        if not geo:
            logger.warning(
                "[infer] 未获取到仿射变换(无 .tfw/.prj 且无内嵌 GeoTIFF 标签),"
                "真实面积/密度将缺失。"
            )
        tract_id = writer.ensure_tract(
            args.acquisition_time or "000000",
            args.location or "demo",
            pixel_w=geo.get("pixel_w") or result.meta.get("width"),
            pixel_h=geo.get("pixel_h") or result.meta.get("height"),
            gsd=geo.get("gsd"),
            geo_area=geo.get("geo_area"),
            area_unit=geo.get("area_unit"),
        )
        # 阶段七: 多源 RGB × CHM 树高(提供 --chm 或 --dsm+--dem 时启用)
        chm_path = getattr(args, "chm", None)
        dsm_path = getattr(args, "dsm", None)
        dem_path = getattr(args, "dem", None)
        if chm_path or (dsm_path and dem_path):
            from .fusion import build_chm_sampler
            from .geo import resolve_geo

            rgb_geo = resolve_geo(
                args.image,
                transform=getattr(source, "transform", None),
                crs=getattr(source, "crs", None),
            )
            sampler = build_chm_sampler(
                chm_path=chm_path, dsm_path=dsm_path, dem_path=dem_path,
                rgb_transform=rgb_geo.transform if rgb_geo else None,
                stat=str(settings.get("fusion.height_stat", "p95")),
            )
            if sampler is not None:
                sampler.annotate(result.detections)
                for _stype, _path in (("chm", chm_path), ("dsm", dsm_path), ("dem", dem_path)):
                    if _path:
                        writer.register_source(tract_id, _stype, _path)
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
    settings, logger, run_id = _bootstrap(getattr(args, "log_level", None))
    from .report import generate_report

    try:
        out = generate_report(
            tract_id=args.tract_id,
            run_id=args.run_id,
            acquisition_time=args.acquisition_time,
            location=args.location,
            fmt=args.format,
            out_dir=args.out,
            with_charts=not args.no_charts,
            db_url=settings.get("db.url", None),
        )
    except ValueError as e:
        logger.error(f"[report] {e}")
        return 2
    if out.get("fallback"):
        logger.warning(f"[report] 降级: {out['fallback']}")
    logger.info(f"[report] 完成[{out['format']}] -> {out['out_path']} (株数={out['data'].tree_count})")
    return 0


def _cmd_batch(args: argparse.Namespace) -> int:
    settings, logger, run_id = _bootstrap(getattr(args, "log_level", None))
    logger.warning("[batch] 仅支持 RGB;批量推理串行执行。")
    from .db import writer
    from .detect import get_detector
    from .engine import RasterImageSource, discover_inputs, run_batch

    arch = args.arch or settings.get("detect.arch", "yolo12")
    try:
        inputs = discover_inputs(args.input_dir, args.glob)
    except FileNotFoundError as e:
        logger.error(f"[batch] {e}")
        return 2
    if not inputs:
        logger.warning(f"[batch] 未匹配到输入文件: {args.input_dir} ({args.glob})")
        return 0

    if arch == "mock":
        detector = get_detector("mock")
    else:
        detector = get_detector(
            arch,
            weights=settings.get("detect.weights", None),
            conf=float(settings.get("detect.conf_threshold", 0.25)),
            iou=float(settings.get("detect.iou_threshold", 0.55)),
            imgsz=int(settings.get("detect.model_input", 1024)),
        )
    res = run_batch(
        inputs, detector,
        acquisition_time=args.acquisition_time or "000000",
        source_factory=lambda p: RasterImageSource(str(p)),
        writer=writer,
        run_kwargs={
            "root_size": int(settings.get("slicing.root_size", 1024)),
            "min_size": int(settings.get("slicing.min_size", 256)),
        },
    )
    logger.info(
        f"[batch] 完成: 成功={res.succeeded} 失败={res.failed} 总株数={res.total_trees} 耗时={res.elapsed_s:.2f}s"
    )
    return 0 if res.failed == 0 else 1


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


def _cmd_track(args: argparse.Namespace) -> int:
    settings, logger, run_id = _bootstrap(getattr(args, "log_level", None))
    import json

    from .db import reader, writer
    from .lifecycle import TreeRecord, track_sequence

    db_url = settings.get("db.url", None)
    tracts = [t for t in reader.list_tracts(url=db_url) if t.get("location") == args.location]
    tracts.sort(key=lambda t: str(t.get("acquisition_time")))
    if not tracts:
        logger.error(f"[track] location={args.location} 无地块")
        return 2
    logger.info(f"[track] location={args.location} 命中 {len(tracts)} 个时相地块")

    snapshots: list[tuple[str, list]] = []
    for t in tracts:
        tid = t["tract_id"]
        run_for = reader.latest_run_for_tract(tid, url=db_url)
        if not run_for:
            logger.warning(f"[track] 地块 {tid} 无观测 run,跳过")
            continue
        obs = reader.fetch_observations(tract_id=tid, run_id=run_for, url=db_url)
        writer.consolidate_tract_trees(tid, run_for, obs, url=db_url)
        recs = []
        for o in obs:
            pt = writer.parse_point(o.get("geom_point"))
            if pt is None:
                continue
            recs.append(TreeRecord(
                key=o["obs_id"], x=pt[0], y=pt[1],
                height=o.get("height"), crown=o.get("crown_area_px"),
                species=o.get("species"),
            ))
        snapshots.append((str(t.get("acquisition_time")), recs))
        logger.info(f"[track] 时相 {t.get('acquisition_time')}: 规范株 {len(recs)} 位")

    if not snapshots:
        logger.error("[track] 无可追踪的时相")
        return 2

    result = track_sequence(
        snapshots, location_cluster=args.location, max_dist=args.max_dist,
        use_hungarian=not args.greedy,
    )
    payload = [
        {
            "individual_id": ind.individual_id,
            "location_cluster": ind.location_cluster,
            "first_seen": ind.first_seen,
            "last_seen": ind.last_seen,
            "status": ind.status,
            "growth_json": json.dumps(ind.to_growth_json(), ensure_ascii=False),
            "members": ind.members,
        }
        for ind in result.individuals
    ]
    writer.persist_individuals(payload, url=db_url)
    alive = sum(1 for i in result.individuals if i.status == "alive")
    rates = [r for r in (i.height_growth_rate() for i in result.individuals) if r is not None]
    avg_rate = sum(rates) / len(rates) if rates else None
    logger.info(
        f"[track] 完成 location={args.location} 时相={len(snapshots)} 个体={result.n_individuals} "
        f"存活={alive} 枯死={result.n_deaths} 新生={result.n_births} 配对={result.n_matched} "
        f"平均生长率={avg_rate if avg_rate is None else round(avg_rate, 3)} m/时相"
    )
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
    p_infer.add_argument("--chm", default=None, help="[阶段七] CHM 冠层高度模型栈格路径(单波段),用于树高")
    p_infer.add_argument("--dsm", default=None, help="[阶段七] DSM 地表高程,与 --dem 配合算 CHM")
    p_infer.add_argument("--dem", default=None, help="[阶段七] DEM 裸地高程,与 --dsm 配合算 CHM")
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
    p_report.add_argument("--tract-id", dest="tract_id", default=None, help="地块 ID")
    p_report.add_argument("--run-id", dest="run_id", default=None, help="限定某次 run")
    p_report.add_argument("--acquisition-time", dest="acquisition_time", default=None, help="地块时相 YYYYMM")
    p_report.add_argument("--location", default=None, help="地块位置标识")
    p_report.add_argument("--format", choices=["md", "csv", "pdf"], default="md", help="输出格式")
    p_report.add_argument("--out", default=None, help="输出目录(默认 <home>/outputs)")
    p_report.add_argument("--no-charts", dest="no_charts", action="store_true", help="不生成图表(PDF)")
    p_report.add_argument(
        "--log-level", dest="log_level", default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="日志级别(默认读配置)",
    )
    p_report.set_defaults(func=_cmd_report)

    p_batch = sub.add_parser("batch", help="批量处理(仅 RGB,串行)")
    p_batch.add_argument("--input-dir", dest="input_dir", required=True, help="输入目录")
    p_batch.add_argument("--glob", default="*.tif", help="文件匹配模式(默认 *.tif)")
    p_batch.add_argument("--arch", choices=["yolo12", "rtdetr", "mock"], default=None, help="模型架构")
    p_batch.add_argument("--acquisition-time", dest="acquisition_time", default=None, help="地块时相 YYYYMM")
    p_batch.add_argument(
        "--log-level", dest="log_level", default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="日志级别(默认读配置)",
    )
    p_batch.set_defaults(func=_cmd_batch)

    p_db = sub.add_parser("db", help="数据库管理")
    p_db.add_argument("db_action", choices=["init", "migrate"], help="动作")
    p_db.set_defaults(func=_cmd_db)

    p_track = sub.add_parser("track", help="单木生命周期追踪(创新点 C)")
    p_track.add_argument("--location", required=True, help="要追踪的地块位置标识(跨多个时相)")
    p_track.add_argument("--max-dist", dest="max_dist", type=float, default=20.0, help="跨时相匹配位置门控(像素,默认 20)")
    p_track.add_argument("--greedy", action="store_true", help="使用贪婪匹配(默认医牛利最优)")
    p_track.add_argument(
        "--log-level", dest="log_level", default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="日志级别(默认读配置)",
    )
    p_track.set_defaults(func=_cmd_track)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
