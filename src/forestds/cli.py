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
    arch: Optional[str] = Option(None, "--arch", help="模型架构 (默认 ultralytics)"),
    acquisition_time: Optional[str] = Option(None, "--acquisition-time", help="地块时相 YYYYmmdd"),
    location: Optional[str] = Option(None, "--location", help="地块位置标识"),
    overlap_rate: Optional[float] = Option(None, "--overlap-rate", help="重叠率 (0.0~1.0)"),
    chm: Optional[str] = Option(None, "--chm", help="CHM 冠层高度模型栅格路径"),
    dsm: Optional[str] = Option(None, "--dsm", help="DSM 地表高程，与 --dem 配合算 CHM"),
    dem: Optional[str] = Option(None, "--dem", help="DEM 裸地高程，与 --dsm 配合算 CHM"),
    las: Optional[str] = Option(None, "--las", help="激光点云 LAS/LAZ 路径"),
    las_grid_size: Optional[float] = Option(None, "--las-grid-size", help="点云网格化分辨率(米)"),
    dem_default: Optional[float] = Option(None, "--dem-default", help="单独 DSM 模式下默认常数 DEM 背景高程"),
    draw_box: Optional[bool] = Option(None, "--draw-box/--no-draw-box", help="是否绘制边界框"),
    export_format: Optional[str] = Option(
        None, "--export-format",
        help="推理完成后自动导出 GIS 图层格式 (geojson / shp / gpkg / csv)，不指定则不导出",
    ),
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
                overlap_rate=overlap_rate, chm=chm, dsm=dsm, dem=dem,
                las=las, las_grid_size=las_grid_size, dem_default=dem_default,
                draw_box=draw_box, export_fmt=export_format,
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
            logger.exception("[infer] 失败: {}", e)
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
            overlap_rate=overlap_rate,
            chm=chm,
            dsm=dsm,
            dem=dem,
            las=las,
            las_grid_size=las_grid_size,
            dem_default=dem_default,
            draw_box=draw_box,
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
    out_dir: Optional[str] = Option(None, "--out-dir", "--out", help="切片输出目录 (默认 <home>/outputs/<YYmmdd_HHMM>_<run_id>/preprocess/tiles__xxx/)"),
    tile_size: Optional[int] = Option(None, "--tile-size", help="手动指定切片边长(不指定则自适应)"),
    overlap_rate: Optional[float] = Option(None, "--overlap-rate", help="手动指定重叠率(0.0~0.5，不指定则自适应)"),
    slice: Optional[bool] = Option(None, "--slice/--no-slice", help="是否激活切片功能"),
    cog: Optional[bool] = Option(None, "--cog/--no-cog", help="是否激活 COG 转换功能"),
    cog_out: Optional[str] = Option(None, "--cog-out", help="COG 转换输出影像路径(默认同级 *_cog.tif)"),
    action: Optional[str] = Option(None, "--action", help="切片行为: slice (执行静态切片：先落盘后推理) | none (执行动态切片：仅计算参数，不落盘，边切边推理)"),
    draw_box: Optional[bool] = Option(None, "--draw-box/--no-draw-box", help="是否在自标定样本图上绘制检测框（用于调试）"),
) -> int:
    settings, run_id = _bootstrap(task_type="preprocess")
    if draw_box is not None:
        settings.data["draw_box"] = draw_box
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
            slice_action=action,
            slice_enable=slice,
            cog_enable=cog,
            cog_out=cog_out,
            tile_size=tile_size,
            overlap_rate=overlap_rate,
            settings=settings,
            run_id=run_id,
            out_dir=out_dir
        )
        
        logger.info("完成预处理: ")
        logger.info(f"运行模式: {res['mode']}")
        logger.info(f"处理后原图路径: {res['image_path']}")
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


@app.command("train", help="模型训练")
def cmd_train(
    data_dir: str = Argument(..., help="数据集目录路径 (VOC/COCO/YOLO)"),
    model: str = Argument(..., help="模型路径 (.yaml 结构配置或 .pt 预训练权重)"),
    cfg: str = Option(
        "configs/ultralytics_train.yaml", "--cfg", "-c",
        help="训练参数配置文件路径"
    ),
    format: str = Option(
        "YOLO", "--format", "-f",
        help="数据集类型 (YOLO / VOC / COCO)"
    ),
    incremental: bool = Option(
        False, "--incremental", "-i",
        help="是否开启增量微调模式"
    ),
    base_dataset: Optional[str] = Option(
        None, "--base-dataset", "-b",
        help="基底主训练集目录路径（用于增量训练时的数据回放，防灾难性遗忘）"
    ),
    base_format: str = Option(
        "YOLO", "--base-format",
        help="基底数据集格式 (YOLO / VOC / COCO)"
    ),
    freeze_layers: int = Option(
        10, "--freeze-layers",
        help="增量微调时冻结的前 N 层骨干网络"
    ),
    epochs: Optional[int] = Option(
        None, "--epochs", "-e",
        help="训练/微调轮数"
    ),
    log_level: Optional[str] = Option(None, "--log-level", help="日志级别(默认读配置)"),
) -> int:
    """YOLO 模型训练命令，支持 VOC / COCO / YOLO 等多格式自适应转换与极简/增量微调训练。"""
    # 如果指定了 base_dataset，自动激活 incremental 模式
    if base_dataset and not incremental:
        incremental = True
        logger.info("检测到指定了 --base-dataset，自动开启增量微调训练模式。")

    # 根据是否是增量模式，决定 task_type
    current_task_type = "train-inc" if incremental else "train"
    
    settings, run_id = _bootstrap(log_level, task_type=current_task_type)
    from .tasks.train import run_train

    try:
        results = run_train(
            data_dir=data_dir,
            model_path=model,
            cfg_path=cfg,
            dataset_format=format,
            run_id=run_id,
            incremental=incremental,
            base_dataset=base_dataset,
            base_format=base_format,
            freeze_layers=freeze_layers,
            epochs=epochs,
            task_type=current_task_type,
        )
        logger.debug(f"[{current_task_type}] 训练已结束。成果保存目录: {results['run_dir']}")
        return 0
    except FileNotFoundError as e:
        logger.error(f"[{current_task_type}] 运行所需文件未找到: {e}")
        return 1
    except ValueError as e:
        logger.error(f"[{current_task_type}] 输入参数非法: {e}")
        return 2
    except Exception as e:
        logger.exception(f"[{current_task_type}] 训练执行遭遇异常: {e}")
        return 1



@app.command("report", help="专业统计报告")
def cmd_report(
    tract_id: Optional[str] = Option(None, "--tract-id", help="地块 ID"),
    run_id: Optional[str] = Option(None, "--run-id", help="限定某次 run"),
    acquisition_time: Optional[str] = Option(None, "--acquisition-time", help="地块时相 YYYYmmdd"),
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

    settings, run_id = _bootstrap(args.log_level, task_type="report")
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


@app.command("export", help="导出检测到的树木空间图层(shp/geojson/gpkg/csv)")
def cmd_export(
    tract_id: Optional[str] = Option(None, "--tract-id", help="地块 ID(默认最新)"),
    run_id: Optional[str] = Option(None, "--run-id", help="限定特定运行(默认最新)"),
    format: str = Option("geojson", "--format", help="导出格式: shp / geojson / gpkg / csv"),
    out: Optional[str] = Option(None, "--out", help="导出路径/目录(默认 outputs 目录)"),
    log_level: Optional[str] = Option(None, "--log-level", help="日志级别(默认读配置)"),
) -> int:
    args = SimpleNamespace(
        tract_id=tract_id, run_id=run_id, format=format, out=out, log_level=log_level
    )

    settings, _ = _bootstrap(args.log_level, task_type="export")
    from .export import export_tract_to_file

    try:
        res = export_tract_to_file(
            tract_id=args.tract_id,
            run_id=args.run_id,
            fmt=args.format,
            out_path=args.out,
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
    input_dir: str = Option(..., "--input-dir", help="输入目录"),
    glob: str = Option("*.tif", "--glob", help="文件匹配模式(默认 *.tif)"),
    arch: Optional[str] = Option(None, "--arch", help="模型架构 (默认 ultralytics)"),
    acquisition_time: Optional[str] = Option(None, "--acquisition-time", help="地块时相 YYYYmmdd"),
    log_level: Optional[str] = Option(None, "--log-level", help="日志级别(默认读配置)"),
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


@app.command("clean", help="清理运行期目录(保留子目录结构，默认不删 models)")
def cmd_clean(
    delete_models: bool = Option(
        False,
        "--delete-models",
        help="是否连同 models 目录下的模型权重一并删除(默认保留)",
    ),
) -> int:
    import shutil
    from . import paths

    root = paths.home_dir()
    logger.info(f"[clean] 开始清理运行期目录: {root}")
    if not root.exists():
        logger.info("[clean] 运行期目录不存在，无需清理。")
        return 0

    for item in root.iterdir():
        if item.is_dir():
            # 保留 models 目录及其内容（除非 delete_models 为 True）
            if item.name == "models" and not delete_models:
                logger.info(f"[clean] 保留模型目录: {item}")
                continue

            logger.info(f"[clean] 清空目录内容: {item}")
            for sub_item in item.iterdir():
                try:
                    if sub_item.is_dir() and not sub_item.is_symlink():
                        shutil.rmtree(sub_item)
                    else:
                        sub_item.unlink()
                except Exception as e:
                    logger.warning(f"[clean] 无法删除 {sub_item}: {e}")
        else:
            try:
                item.unlink()
                logger.info(f"[clean] 删除文件: {item}")
            except Exception as e:
                logger.warning(f"[clean] 无法删除文件 {item}: {e}")

    logger.info("[clean] 清理完成！已保留子目录结构。")
    return 0


tool_app = typer.Typer(help="辅助工具集")


@tool_app.command("draw-bbox", help="给图像画标注框和推理框")
def cmd_draw_bbox(
    image: str = Argument(..., help="图像路径"),
    label: Optional[str] = Option(None, "--label", "-l", help="标注文件路径(YOLO txt/VOC xml/GeoJSON)，若未指定则自动搜寻匹配"),
    with_infer: bool = Option(False, "--with-infer", help="是否在画框中执行静默推理"),
    log_level: Optional[str] = Option(None, "--log-level", help="日志级别"),
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
