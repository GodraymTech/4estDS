"""4estDS CLI。

根命令 ``4estds``,子命令 ``infer / preprocess / train / report / db / batch / track``。
使用 Typer 框架进行命令行解析。
"""
from __future__ import annotations

import sys
import faulthandler
faulthandler.enable()
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


def _bootstrap(level: str | None = None, task_type: str | None = None, to_file: bool = True):
    paths.ensure_home()
    settings = load_settings()
    _, run_id = setup_logging(
        level=level or settings.get("level", "INFO"),
        task_type=task_type,
        to_file=to_file,
    )
    paths.set_run_context(run_id, task_type)
    import sys
    logger.info("执行命令: " + " ".join(sys.argv))
    return settings, run_id




@app.command("infer", help="图像推理")
def cmd_infer(
    images: list[str] = Argument(..., help="输入影像/图像路径(支持 TIFF/PNG/JPG 等)或目录"),
    arch: Optional[str] = Option(None, "--arch", "-a", help="模型架构 (默认 ultralytics)"),
    acquisition_time: Optional[str] = Option(None, "--acquisition-time", "-t", help="地块时相 YYYYmmdd"),
    location: Optional[str] = Option(None, "--location", "-l", help="地块位置标识"),
    tile_size: Optional[int] = Option(None, "--tile-size", "-s", help="手动指定切片边长(不指定则自适应)"),
    overlap_rate: Optional[float] = Option(None, "--overlap-rate", "-r", help="手动指定重叠率(0.0~0.5，不指定则自适应)"),
    chm: Optional[str] = Option(None, "--chm", help="CHM 冠层高度模型栅格路径"),
    dsm: Optional[str] = Option(None, "--dsm", help="DSM 地表高程，与 --dem 配合算 CHM"),
    dem: Optional[str] = Option(None, "--dem", help="DEM 裸地高程，与 --dsm 配合算 CHM"),
    las: Optional[str] = Option(None, "--las", help="激光点云 LAS/LAZ 路径"),
    las_grid_size: Optional[float] = Option(None, "--las-grid-size", help="点云网格化分辨率(米)"),
    dem_default: Optional[float] = Option(None, "--dem-default", help="单独 DSM 模式下默认常数 DEM 背景高程"),
    draw_box: Optional[bool] = Option(None, "--draw-box/--no-draw-box", help="是否绘制边界框 (默认:True)"),
    export_format: Optional[str] = Option(None, "--export-format", "-f", help="推理完成后自动导出 GIS 图层格式 (geojson / shp / gpkg / csv)，不指定则不导出"),
    log_level: Optional[str] = Option(None, "--log-level", help="日志级别(默认读配置)"),
) -> int:
    from pathlib import Path
    from .db import writer
    from .tasks.infer import VALID_EXPORT_FORMATS, run_infer_pipeline

    if export_format and export_format not in VALID_EXPORT_FORMATS:
        logger.error(
            "[infer] 不支持的导出格式 '{}', 可选: {}", export_format, ", ".join(VALID_EXPORT_FORMATS)
        )
        return 2

    settings, run_id = _bootstrap(log_level, task_type="infer") 
    logger.info("[infer] settings snapshot: {}", settings)

    act_draw_box = draw_box if draw_box is not None else settings.get("postprocess.draw_box", True)

    # 路由分支：如果大于 1 个输入路径，或者单个路径是目录，则走批量流程
    is_batch = len(images) > 1 or (len(images) == 1 and Path(images[0]).is_dir())

    if not is_batch:
        image = images[0]
        arch_val = arch or settings.get("detect.arch", "ultralytics")

        logger.info("[infer] run_id={} arch={} image={}", run_id, arch_val, image)
        writer.start_run_log(
            run_id, "infer", model_arch=arch_val, input_path=image,
            params={"arch": arch_val, "image": image},
            url=settings.get("url", None),
        )

        try:
            result = run_infer_pipeline(
                image, run_id=run_id, settings=settings,
                arch=arch_val, acquisition_time=acquisition_time, location=location,
                tile_size=tile_size, overlap_rate=overlap_rate, chm=chm, dsm=dsm, dem=dem,
                las=las, las_grid_size=las_grid_size, dem_default=dem_default,
                draw_box=act_draw_box, export_fmt=export_format,
            )
        except NotImplementedError as e:
            writer.finish_run_log(run_id, "failed", error=str(e), url=settings.get("url", None))
            logger.warning("[infer] {}", e)
            return 0
        except FileNotFoundError as e:
            writer.finish_run_log(run_id, "failed", error=str(e), url=settings.get("url", None))
            logger.error("[infer] 文件未找到: {}", e)
            return 1
        except Exception as e:
            writer.finish_run_log(run_id, "failed", error=str(e), url=settings.get("url", None))
            # 使用 opt(exception=False) 避免 loguru _better_exceptions 尝试 repr 推理帧中的
            # 大型 numpy 数组（如 71k 检测框），该操作会导致 C 层段错误。
            logger.opt(exception=False).error("[infer] 失败: {} — {}", type(e).__name__, e)
            return 1

        logger.info(
            "[infer] 完成！耗时={:.1f}s  瓦片={}/{}  检测={} 株  入库={} 条",
            result["duration_s"], result["tiles_processed"], result["tiles_total"],
            result["fused_count"], result["observations_written"],
        )
        # if result.get("report_path"):
        #     logger.info("[infer] 报告 → {}", result["report_path"])
        # if result.get("export_path"):
        #     logger.info("[infer] 导出 → {}", result["export_path"])
        return 0
    else:
        # 批量预处理推理
        from .tasks.batch import run_batch_pipeline

        batch_summary = run_batch_pipeline(
            images,
            settings=settings,
            arch=arch,
            acquisition_time=acquisition_time,
            location=location,
            tile_size=tile_size,
            overlap_rate=overlap_rate,
            chm=chm,
            dsm=dsm,
            dem=dem,
            las=las,
            las_grid_size=las_grid_size,
            dem_default=dem_default,
            draw_box=act_draw_box,
            export_fmt=export_format,
        )

        if batch_summary.total == 0:
            logger.warning("[infer] 批量推理未处理任何有效影像。")
            return 0
        
        logger.info(
            "[infer] 批量推理完成！总数={} 成功={} 失败={} 累计单木={} 耗时={:.1f}s",
            batch_summary.total, batch_summary.succeeded, batch_summary.failed,
            batch_summary.total_trees, batch_summary.elapsed_s
        )
        return 0 if batch_summary.failed == 0 else 1


@app.command("preprocess", help="影像预处理(自适应切片与 COG 转换)")
def cmd_preprocess(
    image: str = Argument(..., help="输入影像/图像路径(支持 TIFF/PNG/JPG 等)"),
    tile_size: Optional[int] = Option(None, "--tile-size", "-s", help="手动指定切片边长(不指定则自适应)"),
    overlap_rate: Optional[float] = Option(None, "--overlap-rate", "-r", help="手动指定重叠率(0.0~0.5，不指定则自适应)"),
    action: Optional[str] = Option(None, "--action", "-a", help="切片行为: dynamic (边切边推理) | static (静态切片：先落盘后推理) (默认:dynamic)"),
    draw_box: Optional[bool] = Option(None, "--draw-box/--no-draw-box", "-d", help="自标定样本图上是否绘制检测框 (默认:False)"),
    out_dir: Optional[str] = Option(None, "--out-dir", "-o", help="切片输出目录 (默认 `run_dir()`)"),
) -> int:
    settings, run_id = _bootstrap(task_type="preprocess")
    act_action = action if action is not None else settings.get("preprocess.action", "dynamic")
    act_draw_box = draw_box if draw_box is not None else settings.get("preprocess.scope.draw_box", False)

    if "preprocess" not in settings.data:
        settings.data["preprocess"] = {}
    if "scope" not in settings.data["preprocess"]:
        settings.data["preprocess"]["scope"] = {}
    settings.data["preprocess"]["scope"]["draw_box"] = act_draw_box
    logger.info(f"开始预处理输入文件: {image}")

    import os
    from pathlib import Path

    if not os.path.exists(image):
        logger.error(f"输入文件不存在: {image}")
        return 1

    try:
        from .preprocess.pipeline import prepare_inference_image
        
        # 调用统一预处理管道
        res = prepare_inference_image(
            image_path=image,
            slice_action=act_action,
            tile_size=tile_size,
            overlap_rate=overlap_rate,
            settings=settings,
            run_id=run_id,
            out_dir=out_dir
        )
        logger.info("完成预处理: ")
        logger.info(f"运行模式: {res['mode']}")
        logger.info(f"原图路径: {res['image_path']}")
        logger.info(f"切片参数: tile_size={res['tile_size']}px, overlap_rate={res['overlap_rate']:.0%}")
        if res["tiles_dir"]:
            logger.info(f"切片输出目录: {res['tiles_dir']}")
            logger.info(f"静态切片落盘完成: 成功保存 {res['saved_count']} 块瓦片。")
        else:
            logger.info("未生成物理切片。")
            
        return 0
    except FileNotFoundError as e:
        logger.error(f"预处理失败:\n{e}")
        return 1
    except Exception as e:
        logger.exception(f"预处理管道运行失败: {e}")
        return 1


@app.command("preprocess-train", help="针对训练的数据集自适应预处理与规整")
def cmd_preprocess_train(
    data_dir: str = Argument(..., help="新数据集目录路径"),
    old_data_dir: Optional[str] = Option(None, "--old-data-dir", help="增量训练 of 旧数据集目录"),
    new_sample_rate: Optional[float] = Option(None, "--new-sample-rate", help="增量数据集采样率 (默认:1.0)"),
    old_sample_rate: Optional[float] = Option(None, "--old-sample-rate", help="旧数据集采样率 (默认:1.0)"),
    new_ratio_min: Optional[float] = Option(None, "--new-ratio-min", help="合并后'增量数据集'所占的最小比例 (默认:0.1)"),
    neg_ratio: Optional[float] = Option(None, "--neg-ratio", help="负样本占总图像数的比例 (默认:0.1)"),
    out_dir: Optional[str] = Option(None, "--out-dir", "-o", help="输出规整数据集的目录（默认自动生成）"),
) -> int:
    """自适应解析 VOC/COCO/YOLO 数据集，支持多级目录、负样本与增量混合，并输出数据分布报告。"""
    settings, run_id = _bootstrap(task_type="preprocess_train")
    from .tasks.preprocess_train import preprocess_train_dataset

    # 从 settings 加载默认值
    tp_cfg = settings.get("train_preprocess", {})
    act_new_sr = new_sample_rate if new_sample_rate is not None else tp_cfg.get("new_sample_rate", 1.0)
    act_old_sr = old_sample_rate if old_sample_rate is not None else tp_cfg.get("old_sample_rate", 1.0)
    act_new_rm = new_ratio_min if new_ratio_min is not None else tp_cfg.get("new_ratio_min", 0.1)
    act_neg_r = neg_ratio if neg_ratio is not None else tp_cfg.get("neg_ratio", 0.1)

    try:
        preprocess_train_dataset(
            data_dir=data_dir,
            old_data_dir=old_data_dir,
            new_sample_rate=act_new_sr,
            old_sample_rate=act_old_sr,
            new_ratio_min=act_new_rm,
            neg_ratio=act_neg_r,
            dest_dir=out_dir,
        )
        logger.info("[preprocess-train] 数据集自适应预处理与规整成功！")
        return 0
    except Exception as e:
        logger.exception(f"[preprocess-train] 数据集预处理执行遭遇异常: {e}")
        return 1


@app.command("train", help="模型训练")
def cmd_train(
    data_dir: str = Argument(..., help="数据集目录路径 (VOC/COCO/YOLO/混合)"),
    model: str = Argument(..., help="模型路径 (.yaml 结构配置或 .pt 预训练权重)"),
    cfg: str = Option("configs/ultralytics_train.yaml", "--cfg", "-c",help="训练参数配置文件路径"),
    format: str = Option("YOLO", "--format", "-f",help="数据集类型 (YOLO / VOC / COCO)"),
    old_data_dir: Optional[str] = Option(None, "--old-data-dir", help="增量训练的旧数据集目录"),
    new_sample_rate: Optional[float] = Option(None, "--new-sample-rate", help="增量数据集采样率 (默认:1.0)"),
    old_sample_rate: Optional[float] = Option(None, "--old-sample-rate", help="旧数据集采样率 (默认:1.0)"),
    new_ratio_min: Optional[float] = Option(None, "--new-ratio-min", help="合并后'增量数据集'所占的最小比例 (默认:0.1)"),
    neg_ratio: Optional[float] = Option(None, "--neg-ratio", help="负样本占总图像数的比例 (默认:0.1)"),
    log_level: Optional[str] = Option(None, "--log-level", help="日志级别"),
) -> int:
    """YOLO 模型训练命令，支持 VOC / COCO / YOLO 等多格式自适应转换与极简训练。"""
    settings, run_id = _bootstrap(log_level, task_type="train")
    from .tasks.train import run_train

    try:
        results = run_train(
            data_dir=data_dir,
            model_path=model,
            cfg_path=cfg,
            dataset_format=format,
            run_id=run_id,
            old_data_dir=old_data_dir,
            new_sample_rate=new_sample_rate,
            old_sample_rate=old_sample_rate,
            new_ratio_min=new_ratio_min,
            neg_ratio=neg_ratio,
        )
        logger.debug(f"[train] 训练已结束。成果保存目录: {results['run_dir']}")
        return 0
    except FileNotFoundError as e:
        logger.error(f"[train] 运行所需文件未找到: {e}")
        return 1
    except ValueError as e:
        logger.error(f"[train] 输入参数非法: {e}")
        return 2
    except Exception as e:
        logger.exception(f"[train] 训练执行遭遇异常: {e}")
        return 1




@app.command("report", help="专业统计报告")
def cmd_report(
    tract_id: Optional[str] = Option(None, "--tract-id", help="地块 ID"),
    run_id: Optional[str] = Option(None, "--run-id", help="限定某次 run"),
    acquisition_time: Optional[str] = Option(None, "--acquisition-time", help="地块时相 YYYYmmdd"),
    location: Optional[str] = Option(None, "--location", help="地块位置标识"),
    format: Optional[str] = Option(None, "--format", help="输出格式 (md / csv / pdf) (默认:md)"),
    out: Optional[str] = Option(None, "--out", help="输出目录(默认 <home>/outputs)"),
    no_charts: Optional[bool] = Option(None, "--no-charts/--charts", help="是否不生成图表(PDF) (默认:False)"),
    log_level: Optional[str] = Option(None, "--log-level", help="日志级别(默认读配置)"),
) -> int:
    settings, run_id = _bootstrap(log_level, task_type="report")
    from .report import generate_report

    act_format = format if format is not None else settings.get("report.format", "md")
    if no_charts is not None:
        act_no_charts = no_charts
    else:
        act_no_charts = not settings.get("report.with_charts", True)

    try:
        out_res = generate_report(
            tract_id=tract_id,
            run_id=run_id,
            acquisition_time=acquisition_time,
            location=location,
            fmt=act_format,
            out_dir=out,
            with_charts=not act_no_charts,
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


@app.command("export", help="导出检测到的树木空间图层(shp/geojson/gpkg/csv)")
def cmd_export(
    tract_id: Optional[str] = Option(None, "--tract-id", help="地块 ID(默认最新)"),
    run_id: Optional[str] = Option(None, "--run-id", help="限定特定运行(默认最新)"),
    format: Optional[str] = Option(None, "--format", help="导出格式: shp / geojson / gpkg / csv (默认:geojson)"),
    out: Optional[str] = Option(None, "--out", help="导出路径/目录(默认 outputs 目录)"),
    log_level: Optional[str] = Option(None, "--log-level", help="日志级别(默认读配置)"),
) -> int:
    settings, _ = _bootstrap(log_level, task_type="export")
    from .export import export_tract_to_file

    act_format = format if format is not None else settings.get("export.default_format", "geojson")

    try:
        res = export_tract_to_file(
            tract_id=tract_id,
            run_id=run_id,
            fmt=act_format,
            out_path=out,
            db_url=settings.get("url", None),
        )
        if res.get("fallback"):
            logger.warning(f"[export] 降级: {res['fallback']}")
        logger.info(
            f"[export] 导出成功[{res['format']}]，共计 {res['count']} 株单木 -> {res['out_path']}"
        )
        return 0
    except Exception as e:
        logger.error(f"[export] 导出失败: {e}")
        return 1


@app.command("batch", help="批量处理(仅 RGB,串行)")
def cmd_batch(
    input_dir: str = Option(..., "--input-dir", "-i", help="输入目录"),
    glob: str = Option("*.tif", "--glob", "-g", help="文件匹配模式(默认 *.tif)"),
    arch: Optional[str] = Option(None, "--arch", "-a", help="模型架构 (默认 ultralytics)"),
    acquisition_time: Optional[str] = Option(None, "--acquisition-time", "-t", help="地块时相 YYYYmmdd"),
    log_level: Optional[str] = Option(None, "--log-level", "-l", help="日志级别(默认读配置)"),
) -> int:
    args = SimpleNamespace(
        input_dir=input_dir, glob=glob, arch=arch, acquisition_time=acquisition_time, log_level=log_level
    )

    settings, run_id = _bootstrap(args.log_level, task_type="batch")
    logger.warning("[batch] 仅支持 RGB;批量推理串行执行。")
    from pathlib import Path
    from .tasks.batch import run_batch_pipeline

    arch_val = args.arch or settings.get("arch", "ultralytics")
    base = Path(args.input_dir)
    if not base.exists():
        logger.error(f"[batch] 输入目录不存在: {base}")
        return 2

    # 提取支持的有效影像格式
    valid_suffixes = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}
    inputs = sorted(
        str(p.resolve()) for p in base.glob(args.glob)
        if p.is_file() and p.suffix.lower() in valid_suffixes
    )
    if not inputs:
        logger.warning(f"[batch] 未匹配到输入文件: {args.input_dir} ({args.glob})")
        return 0

    res = run_batch_pipeline(
        inputs,
        settings=settings,
        arch=arch_val,
        acquisition_time=args.acquisition_time,
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

    settings, run_id = _bootstrap(task_type="db")
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

    settings, run_id = _bootstrap(args.log_level, task_type="track")
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


@app.command("clean", help="清理运行期目录(支持多级别清理，智能垃圾回收)")
def cmd_clean(
    level: str = Option(
        "standard",
        "--level",
        "-l",
        help="清理级别: standard (默认：与日志文件对齐) / reset (仅保留 models 和 config子目录) / deep (强制彻底清空 home_dir)",
    ),
    yes: bool = Option(
        False,
        "--yes",
        "-y",
        help="在 deep 级别清理时直接执行免去交互确认",
    ),
) -> int:
    from .tasks.clean import run_clean_pipeline
    from . import paths
    import typer
    
    level = level.lower().strip()
    if level not in ("deep", "reset", "standard"):
        logger.error(f"[clean] 不支持的清理级别 '{level}'，可选: standard, reset, deep")
        return 1

    if level == "deep" and not yes:
        typer.secho(
            "⚠️  警告 (CRITICAL WARNING) ⚠️\n"
            f"deep 清理级别将彻底清空您的整个运行期根目录 [{paths.home_dir()}]！\n"
            "这会永久清空您的所有本地数据库记录、模型权重 (models) 以及本地配置文件！此操作不可逆！",
            fg=typer.colors.RED,
            bold=True,
        )
        confirm = typer.confirm("您确定要继续此操作吗？", default=False)
        if not confirm:
            logger.info("[clean] 操作被用户取消。")
            return 1

    logger.info(f"[clean] 开始执行 [{level}] 级别的清理管线...")
    try:
        res = run_clean_pipeline(level=level)
    except Exception as e:
        logger.error(f"[clean] 清理过程发生致命错误: {e}")
        return 1

    if level == "deep":
        logger.info(
            f"[clean] 深度清理完成！共删除文件 {res['deleted_files_count']} 个，"
            f"释放磁盘空间 {res['freed_bytes'] / 1024 / 1024:.2f} MB"
        )
    elif level == "reset":
        logger.info(
            f"[clean] 重置完成！已保留 models 与 config 目录。共删除文件 {res['deleted_files_count']} 个，"
            f"释放磁盘空间 {res['freed_bytes'] / 1024 / 1024:.2f} MB"
        )
    else:  # standard (smart GC)
        logger.info("[clean] 智能垃圾回收 (standard) 完成！")
        
        if res.get("deleted_runs"):
            logger.info("🗑️  已清理的历史运行记录 (run_id):")
            for run in res["deleted_runs"]:
                logger.info(f"  - {run}")
        
        if res.get("deleted_tracts"):
            logger.info("🗺️  已清理的无用关联地块 (tract_id):")
            for tract in res["deleted_tracts"]:
                logger.info(f"  - {tract}")
                
        if res.get("deleted_outputs"):
            logger.info("📂  已清理的无用输出子目录:")
            for folder in res["deleted_outputs"]:
                logger.info(f"  - {folder}")
        
        db_stats = res.get("deleted_db_stats", {})
        db_by_tract = res.get("deleted_db_by_tract", {})
        
        # 1. 打印按地块进行统计的单木信息删除明细
        obs_by_t = db_by_tract.get("tree_observations", {})
        trees_by_t = db_by_tract.get("tract_trees", {})
        affected_tracts = set(obs_by_t.keys()) | set(trees_by_t.keys())
        if affected_tracts:
            logger.info("🌲  单木空间观测清理明细 (按地块统计):")
            for tid in affected_tracts:
                obs_cnt = obs_by_t.get(tid, 0)
                tree_cnt = trees_by_t.get(tid, 0)
                if obs_cnt > 0 or tree_cnt > 0:
                    logger.info(f"  - 地块 [{tid}]: 删除了 {obs_cnt} 条原始观测, {tree_cnt} 条规范单木")
        
        # 2. 打印其他表的删除统计 (排除已按地块/明细统计的表)
        other_tables_printed = False
        for table_name, deleted_count in db_stats.items():
            if table_name in ("tree_observations", "tract_trees", "run_logs"):
                continue
            if deleted_count > 0:
                if not other_tables_printed:
                    logger.info("📊  其它数据库表记录清理汇总:")
                    other_tables_printed = True
                logger.info(f"  - [{table_name}] 删除了 {deleted_count} 行记录")
                    
        logger.info(
            f"💾  物理存储：共清理文件 {res['deleted_files_count']} 个，"
            f"释放磁盘空间 {res['freed_bytes'] / 1024 / 1024:.2f} MB"
        )
        
    return 0


tool_app = typer.Typer(help="辅助工具集")


@tool_app.command("draw-bbox", help="给图像画标注框和推理框")
def cmd_draw_bbox(
    image: str = Argument(..., help="图像路径"),
    label: Optional[str] = Option(None, "--label", "-l", help="标注文件路径(YOLO txt/VOC xml/GeoJSON)，若未指定则自动搜寻匹配"),
    with_infer: bool = Option(False, "--with-infer", "-i", help="是否在画框中执行静默推理"),
    log_level: Optional[str] = Option(None, "--log-level", "-l", help="日志级别"),
) -> int:
    settings, _ = _bootstrap(level=log_level, task_type="draw-bbox", to_file=False)
    from .utils import draw_bbox_main
    return draw_bbox_main(image, label, with_infer, settings)


@tool_app.command("draw-dsm", help="基于 DSM 高程从影像中提取并画出冠幅轮廓线")
def cmd_draw_dsm(
    image: str = Argument(..., help="正射影像 DOM TIFF 路径"),
    dsm: str = Argument(..., help="数字表面模型 DSM TIFF 路径"),
    log_level: Optional[str] = Option(None, "--log-level", help="日志级别"),
) -> int:
    _, _ = _bootstrap(level=log_level, task_type="draw-dsm", to_file=False)
    from .utils import draw_dsm_main
    return draw_dsm_main(image, dsm)


@tool_app.command("standardize-ds", help="将数据集目录改造成适合 Ultralytics YOLO 训练的新目录结构")
def cmd_standardize_dataset(
    source: str = Argument(..., help="输入的数据集源目录"),
    dest: Optional[str] = Option(None, "--dest", "-d", help="规整规范化后的输出目标目录，若不指定，默认设为源目录附加 _standard 后缀"),
    format: str = Option("auto", "--format", "-f", help="数据集原始格式 (auto/YOLO/VOC/COCO)"),
    split_ratio: float = Option(0.8, "--split-ratio", "-r", help="无预先划分的数据集 train 占比，默认 0.8 (即 8:2)"),
    workers: Optional[int] = Option(None, "--workers", "-w", help="并行工作进程数，默认自动匹配 CPU 核心数"),
    log_level: Optional[str] = Option(None, "--log-level", help="日志级别"),
) -> int:
    settings, _ = _bootstrap(level=log_level, task_type="standardize-ds", to_file=False)
    from .utils import standardize_ds
    try:
        standardize_ds(
            source_dir=source,
            dest_dir=dest,
            dataset_format=format,
            split_ratio=split_ratio,
            num_workers=workers
        )
        return 0
    except Exception as e:
        logger.exception(f"执行 standardize-ds 失败: {e}")
        return 1


@tool_app.command("crop-tiff", help="从 TIFF 影像手动抠图 【若为训练/推理准备大批量裁剪图, 请使用「preprocess」子命令】")
def cmd_crop_tiff(
    image: str = Argument(..., help="输入的 TIFF 影像路径"),
    dest: Optional[str] = Option(None, "--dest", "-d", help="输出目标目录，若不指定，默认设为源图像同级 _crops 目录"),
    num_crops: int = Option(3, "--num-crops", "-n", help="[优先级低于 '-v'] 裁剪张数。⚠️: 0 表示只从大图中心裁一张"),
    size: int = Option(5000, "--size", "-s", help="[优先级低于 '-v'] 裁剪边长大小 (像素)"),
    nodata_tolerance: float = Option(0.05, "--nodata-tolerance", "-t", help="[优先级低于 '-v'] 允许的 nodata 占比上限 (0.0 - 1.0)"),
    vector: Optional[str] = Option(None, "--vector", "-v", help="输入的矢量文件路径 (如 .shp, .geojson 等，若指定则启用'按图索骥模式')"),
    log_level: Optional[str] = Option(None, "--log-level", help="日志级别"),
) -> int:
    settings, _ = _bootstrap(level=log_level, task_type="crop-tiff", to_file=False) 
    from .utils import crop_tiff_main
    try:
        return crop_tiff_main(
            input_path=image,
            output_dir=dest,
            num_crops=num_crops,
            size=size,
            nodata_tolerance=nodata_tolerance,
            vector_path=vector
        )
    except Exception as e:
        logger.exception(f"执行 crop-tiff 失败: {e}")
        return 1


app.add_typer(tool_app, name="tool")


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
