"""4estDS CLI。

根命令 ``4estds``,子命令 ``infer / preprocess / train / report / db / batch / track``。
使用 Typer 框架进行命令行解析。
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Optional

import click
import typer
from typer import Argument, Option

from loguru import logger
from . import __codename__, __version__, paths
from .config import load_settings
from .logging_setup import setup_logging

app = typer.Typer(
    help="4estDS - 林木智能检测系统 (forest detection system)",
    pretty_exceptions_enable=False
)


def _bootstrap(level: str | None = None):
    paths.ensure_home()
    settings = load_settings()
    _, run_id = setup_logging(
        level=level or settings.get("level", "INFO")
    )
    return settings, run_id


@app.command("infer", help="图像推理")
def cmd_infer(
    image: Optional[str] = Option(None, "--image", help="输入图像路径"),
    arch: Optional[str] = Option(None, "--arch", help="模型架构 (yolo12 / rtdetr)"),
    acquisition_time: Optional[str] = Option(None, "--acquisition-time", help="地块时相 YYYYMM"),
    location: Optional[str] = Option(None, "--location", help="地块位置标识"),
    overlap_rate: Optional[float] = Option(None, "--overlap-rate", help="重叠率 (0.0~1.0，如0.15代表15%)"),
    chm: Optional[str] = Option(None, "--chm", help="[阶段七] CHM 冠层高度模型栈格路径(单波段),用于树高"),
    dsm: Optional[str] = Option(None, "--dsm", help="[阶段七] DSM 地表高程,与 --dem 配合算 CHM"),
    dem: Optional[str] = Option(None, "--dem", help="[阶段七] DEM 裸地高程,与 --dsm 配合算 CHM"),
    log_level: Optional[str] = Option(None, "--log-level", help="日志级别(默认读配置)"),
    draw_box: Optional[bool] = Option(None, "--draw-box/--no-draw-box", help="是否绘制边界框并保存结果图像"),
) -> int:
    import time

    args = SimpleNamespace(
        image=image, arch=arch, acquisition_time=acquisition_time, location=location,
        overlap_rate=overlap_rate, chm=chm, dsm=dsm, dem=dem, log_level=log_level, draw_box=draw_box
    )

    settings, run_id = _bootstrap(args.log_level)
    arch_val = args.arch or settings.get("arch", "yolo12")
    from .db import writer
    from .detect import get_detector
    from .engine import run_inference

    logger.info(f"[infer] run_id={run_id} arch={arch_val} image={args.image}")
    writer.start_run_log(
        run_id, "infer", model_arch=arch_val, input_path=args.image,
        params={"arch": arch_val, "image": args.image},
    )
    t0 = time.time()
    source = None
    try:
        if not args.image:
            logger.error("[infer] 真实推理需要 --image")
            writer.finish_run_log(run_id, "failed", error="missing --image")
            return 2
        from .engine import RasterImageSource

        detector = get_detector(
            arch_val,
            weights=settings.get(f"detect.models.{arch_val}.weights", settings.get("detect.weights")),
            conf=float(settings.get("conf_threshold", 0.25)),
            iou=float(settings.get("detect.iou_threshold", 0.6)),
            imgsz=int(settings.get("model_input", 1024)),
            device=settings.get("device", None),
        )
        source = RasterImageSource(args.image)

        result = run_inference(
            source, detector,
            root_size=int(settings.get("root_size", 1024)),
            min_size=int(settings.get("min_size", 256)),
            conf_thr=float(settings.get("conf_threshold", 0.25)),
            iou_thr=float(settings.get("detect.iou_threshold", 0.6)),
            overlap_rate=float(
                args.overlap_rate
                if args.overlap_rate is not None
                else settings.get("default_overlap", 0.2)
            ),
            conf_type=str(settings.get("conf_type", "max")),
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
            args.location or "default",
            pixel_w=geo.get("pixel_w") or result.meta.get("width"),
            pixel_h=geo.get("pixel_h") or result.meta.get("height"),
            gsd=geo.get("gsd"),
            geo_area=geo.get("geo_area"),
            area_unit=geo.get("area_unit"),
        )
        # 阶段七: 多源 RGB × CHM 树高(提供 --chm 或 --dsm+--dem 时启用)
        chm_path = args.chm
        dsm_path = args.dsm
        dem_path = args.dem
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
                stat=str(settings.get("height_stat", "p95")),
            )
            if sampler is not None:
                sampler.annotate(result.detections)
                for _stype, _path in (("chm", chm_path), ("dsm", dsm_path), ("dem", dem_path)):
                    if _path:
                        writer.register_source(tract_id, _stype, _path)
        written = writer.write_observations(tract_id, run_id, result.detections)
        
        # 绘制检测框输出保存（系统架构复用 visualize 模块）
        do_draw = args.draw_box if args.draw_box is not None else settings.get("draw_box", False)
        if do_draw:
            from .visualize import draw_detections_on_image
            from pathlib import Path
            out_dir = paths.outputs_dir()
            out_dir.mkdir(parents=True, exist_ok=True)
            vis_out = out_dir / f"{Path(args.image).stem}_detected.jpg"
            draw_detections_on_image(args.image, result.detections, output_path=vis_out)
            logger.info(f"[infer] 检测框结果图已保存至: {vis_out}")
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


@app.command("preprocess", help="影像预处理(自适应切片与 COG 转换)")
def cmd_preprocess(
    image: str = Argument(..., help="输入影像/图像路径(支持 TIFF/PNG/JPG 等)"),
    out_dir: Optional[str] = Option(None, "--out-dir", "--out", help="切片输出目录 (默认 <home>/outputs/preprocess/tiles__xxx/)"),
    tile_size: Optional[int] = Option(None, "--tile-size", help="手动指定切片边长(不指定则自适应)"),
    overlap_rate: Optional[float] = Option(None, "--overlap-rate", help="手动指定重叠率(0.0~0.5，不指定则自适应)"),
    slice: Optional[bool] = Option(None, "--slice/--no-slice", help="是否激活切片功能"),
    cog: Optional[bool] = Option(None, "--cog/--no-cog", help="是否激活 COG 转换功能"),
    cog_out: Optional[str] = Option(None, "--cog-out", help="COG 转换输出影像路径(默认同级 *_cog.tif)"),
    action: Optional[str] = Option(None, "--action", help="切片行为: slice (切片落盘) | none (仅计算参数，不落盘)"),
    draw_box: Optional[bool] = Option(None, "--draw-box/--no-draw-box", help="是否在自标定样本图上绘制检测框（用于调试）"),
) -> int:
    settings, run_id = _bootstrap()
    if draw_box is not None:
        settings.data["draw_box"] = draw_box
    logger.info(f"开始预处理输入文件: {image}")

    import os
    from pathlib import Path

    if not os.path.exists(image):
        logger.error(f"输入文件不存在: {image}")
        return 1

    is_tiff = image.lower().endswith((".tif", ".tiff"))

    # 1. 读取配置（消除层级字典，通过 Settings 扁平安全获取）
    do_cog = cog if cog is not None else settings.get("preprocess.cog.enable", True)
    do_slice = slice if slice is not None else settings.get("preprocess.slice.enable", True)
    slice_action = action if action is not None else settings.get("preprocess.slice.action", "slice")

    # ---- 第一阶段: COG 检测与转换 ----
    if is_tiff and do_cog:
        from .preprocess.cog import check_cog_format, convert_to_cog
        status = check_cog_format(image)
        logger.info(f"影像 COG 状态检测结果: {status}")
        
        if status != "cog":
            if not cog_out:
                p = Path(image)
                out_suffix = settings.get("out_suffix", "_cog.tif") or "_cog.tif"
                cog_out_path = p.parent / f"{p.stem}{out_suffix}"
            else:
                cog_out_path = Path(cog_out)

            success = convert_to_cog(
                image,
                cog_out_path,
                block_size=int(settings.get("block_size", 512)),
                compress=str(settings.get("compress", "deflate")),
                resampling=str(settings.get("resampling", "nearest")),
                min_overview_dim=int(settings.get("min_overview_dim", 256))
            )
            if success:
                logger.info(f"COG 转换成功，后续切片将切换至新影像: {cog_out_path.name}")
                image = str(cog_out_path)
            else:
                logger.error("COG 转换失败，将尝试基于原影像进行切片。")
        else:
            logger.info("影像已经是标准 COG 格式，无需转换。")

    # ---- 第二阶段: 切片决策网格计算与执行 ----
    if do_slice:
        # 获取图像宽高
        width, height = 0, 0
        if is_tiff:
            try:
                import rasterio
                with rasterio.open(image) as src:
                    width, height = src.width, src.height
            except Exception:
                pass
        
        if width == 0 or height == 0:
            try:
                from PIL import Image
                with Image.open(image) as img:
                    width, height = img.size
            except Exception as e:
                logger.error(f"无法打开影像以读取像素大小: {e}")
                return 1

        min_dim = min(width, height)
        if min_dim < 2560:
            logger.info(f"图像较短边 {min_dim}px < 2560px，跳过切片逻辑。")
            return 0

        t_size = tile_size
        r_ov = overlap_rate

        # 当输入是 TIFF，且启用了自标定，且用户未手动指定参数时
        if is_tiff and settings.get("preprocess.slice.scope.enable", True) and (t_size is None or r_ov is None):
            logger.info("TIFF 格式触发 SCOPE 尺度空间自标定...")
            from .detect import get_detector
            from .preprocess.scope import run_scope_calibration

            arch_val = settings.get("arch", "yolo12")
            detector = get_detector(
                arch=arch_val,
                weights=settings.get(f"detect.models.{arch_val}.weights", settings.get("detect.weights")),
                conf=float(settings.get("conf_threshold", 0.25)),
                iou=float(settings.get("detect.iou_threshold", 0.6)),
                imgsz=int(settings.get("model_input", 1024)),
            )

            resolved_tile, resolved_overlap_rate = run_scope_calibration(
                image, detector, settings, run_id=run_id
            )

            if t_size is None:
                t_size = resolved_tile
            if r_ov is None:
                r_ov = resolved_overlap_rate

            logger.info(f"SCOPE 自标定决策：tile_size={t_size}px, overlap_rate={r_ov:.2%}")
        else:
            # 非 TIFF 图像，或者用户指定了切片大小，或者关闭了自标定
            if t_size is None:
                t_size = int(settings.get("default_tile", 640))
            if r_ov is None:
                r_ov = float(settings.get("default_overlap", 0.2))
            logger.info(f"采用切片默认参数：tile_size={t_size}px, overlap_rate={r_ov:.2%}")

        # 判断切片落盘行为
        if slice_action == "slice":
            from .preprocess.tiling import execute_slicing
            save_quality = int(settings.get("save_quality", 95))
            saved_count = execute_slicing(
                image_path=image,
                out_dir=out_dir,
                tile_size=t_size,
                overlap_rate=r_ov,
                run_id=run_id,
                save_quality=save_quality
            )
            logger.info(f"均匀切片落盘完成: 成功保存 {saved_count} 块瓦片。")
        else:
            logger.info(f"根据配置 action={slice_action}，跳过切片文件落盘 (等待基于 COG 的 on-the-fly 动态切片)。")

    return 0


@app.command("train", help="模型训练(feature-gated)")
def cmd_train() -> int:
    _, run_id = _bootstrap()
    logger.info(f"[train] run_id={run_id} (feature-gated)")
    logger.info("[train] TODO: 训练模块按功能授权解锁(阶段八)")
    return 0


@app.command("report", help="专业统计报告")
def cmd_report(
    tract_id: Optional[str] = Option(None, "--tract-id", help="地块 ID"),
    run_id: Optional[str] = Option(None, "--run-id", help="限定某次 run"),
    acquisition_time: Optional[str] = Option(None, "--acquisition-time", help="地块时相 YYYYMM"),
    location: Optional[str] = Option(None, "--location", help="地块位置标识"),
    format: str = Option("md", "--format", help="输出格式 (md / csv / pdf)"),
    out: Optional[str] = Option(None, "--out", help="输出目录(默认 <home>/outputs)"),
    no_charts: bool = Option(False, "--no-charts", help="不生成图表(PDF)"),
    log_level: Optional[str] = Option(None, "--log-level", help="日志级别(默认读配置)"),
) -> int:
    args = SimpleNamespace(
        tract_id=tract_id, run_id=run_id, acquisition_time=acquisition_time,
        location=location, format=format, out=out, no_charts=no_charts, log_level=log_level
    )

    settings, run_id = _bootstrap(args.log_level)
    from .report import generate_report

    try:
        out_res = generate_report(
            tract_id=args.tract_id,
            run_id=args.run_id,
            acquisition_time=args.acquisition_time,
            location=args.location,
            fmt=args.format,
            out_dir=args.out,
            with_charts=not args.no_charts,
            db_url=settings.get("url", None),
        )
    except ValueError as e:
        logger.error(f"[report] {e}")
        return 2
    if out_res.get("fallback"):
        logger.warning(f"[report] 降级: {out_res['fallback']}")
    logger.info(
        f"[report] 完成[{out_res['format']}] -> {out_res['out_path']} (株数={out_res['data'].tree_count})"
    )
    return 0


@app.command("batch", help="批量处理(仅 RGB,串行)")
def cmd_batch(
    input_dir: str = Option(..., "--input-dir", help="输入目录"),
    glob: str = Option("*.tif", "--glob", help="文件匹配模式(默认 *.tif)"),
    arch: Optional[str] = Option(None, "--arch", help="模型架构 (yolo12 / rtdetr)"),
    acquisition_time: Optional[str] = Option(None, "--acquisition-time", help="地块时相 YYYYMM"),
    log_level: Optional[str] = Option(None, "--log-level", help="日志级别(默认读配置)"),
) -> int:
    args = SimpleNamespace(
        input_dir=input_dir, glob=glob, arch=arch, acquisition_time=acquisition_time, log_level=log_level
    )

    settings, run_id = _bootstrap(args.log_level)
    logger.warning("[batch] 仅支持 RGB;批量推理串行执行。")
    from .db import writer
    from .detect import get_detector
    from .engine import RasterImageSource, discover_inputs, run_batch

    arch_val = args.arch or settings.get("arch", "yolo12")
    try:
        inputs = discover_inputs(args.input_dir, args.glob)
    except FileNotFoundError as e:
        logger.error(f"[batch] {e}")
        return 2
    if not inputs:
        logger.warning(f"[batch] 未匹配到输入文件: {args.input_dir} ({args.glob})")
        return 0

    detector = get_detector(
        arch_val,
        weights=settings.get(f"detect.models.{arch_val}.weights", settings.get("detect.weights")),
        conf=float(settings.get("conf_threshold", 0.25)),
        iou=float(settings.get("detect.iou_threshold", 0.55)),
        imgsz=int(settings.get("model_input", 1024)),
    )
    res = run_batch(
        inputs, detector,
        acquisition_time=args.acquisition_time or "000000",
        source_factory=lambda p: RasterImageSource(str(p)),
        writer=writer,
        run_kwargs={
            "root_size": int(settings.get("root_size", 1024)),
            "min_size": int(settings.get("min_size", 256)),
        },
    )
    logger.info(
        f"[batch] 完成: 成功={res.succeeded} 失败={res.failed} 总株数={res.total_trees} 耗时={res.elapsed_s:.2f}s"
    )
    return 0 if res.failed == 0 else 1


@app.command("db", help="数据库管理")
def cmd_db(
    db_action: str = Argument(..., help="动作 (init / migrate)"),
) -> int:
    args = SimpleNamespace(db_action=db_action)

    settings, run_id = _bootstrap()
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


@app.command("track", help="单木生命周期追踪(创新点 C)")
def cmd_track(
    location: str = Option(..., "--location", help="要追踪的地块位置标识(跨多个时相)"),
    max_dist: float = Option(20.0, "--max-dist", help="跨时相匹配位置门控(像素,默认 20)"),
    greedy: bool = Option(False, "--greedy", help="使用贪婪匹配(默认匈牙利最优)"),
    log_level: Optional[str] = Option(None, "--log-level", help="日志级别(默认读配置)"),
) -> int:
    args = SimpleNamespace(
        location=location, max_dist=max_dist, greedy=greedy, log_level=log_level
    )

    settings, run_id = _bootstrap(args.log_level)
    import json

    from .db import reader, writer
    from .lifecycle import TreeRecord, track_sequence

    db_url = settings.get("url", None)
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


def version_callback(value: bool):
    if value:
        print(f"{__codename__} {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: Optional[bool] = Option(
        None,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="显示版本并退出",
    )
):
    pass


def main(argv: list[str] | None = None) -> int:
    try:
        res = app(args=argv if argv is not None else sys.argv[1:], standalone_mode=False)
        if isinstance(res, int):
            return res
        return 0
    except typer.Exit as e:
        return e.exit_code
    except (click.ClickException, typer._click.exceptions.ClickException) as e:
        e.show()
        return e.exit_code
    except (typer.Abort, click.Abort):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
