"""批量推理任务编排（tasks 层）。

核心模型：一次批量作业 = 一串**各自携带完整参数**的待命项，按顺序串行执行。
「单图直接推理」即长度为 1 的批量，本层不再区分两种作业形态。

提供：
- ``BatchItemSpec``: 一条待命项的参数规格，与 ``run_infer_pipeline`` 入参一一对应
- ``resolve_images``: 把混合的文件/目录输入扁平化为去重排序的影像列表（CLI 展开目录用）
- ``run_batch_pipeline``: 串行批量推理；单条异常不阻断后续，用户终止时按语义善后

终止善后语义（与前端「一键终止」一致）：
- 已跑完的 -> ``succeeded``，成果保留不回滚
- 正在跑、被夹断的 -> ``failed``（子 run 写入终态，不会僵在 running）
- 尚未开始的 -> ``canceled``（不产生脏 run 记录）
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger as log

from ..logging_setup import new_run_id

# 支持的可处理影像后缀
_VALID_SUFFIXES = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}

# 待命项终态
ITEM_SUCCEEDED = "succeeded"
ITEM_FAILED = "failed"
ITEM_CANCELED = "canceled"


@dataclass(slots=True)
class BatchItemSpec:
    """一条待命项：一张影像 + 它自己的一整套推理参数。

    故意不依赖 ``contracts``：本层是纯粹的任务编排，可被 CLI / 单测 直接调用而
    无需引入 pydantic 契约层（依赖倒置）。
    """

    image_path: str
    arch: str | None = None
    phase_id: str | None = None
    tract_id: str | None = None
    tile_size: int | None = None
    overlap_rate: float | None = None
    chm: str | None = None
    dsm: str | None = None
    dem: str | None = None
    las: str | None = None
    las_grid_size: float | None = None
    dem_default: float | None = None
    draw_box: bool | None = None
    export_fmt: str | None = None
    publish: bool = False

    @property
    def display_tract_key(self) -> str:
        """用于日志/汇总展示的地块键；未显式指定时回落文件名 stem。"""
        explicit = (self.tract_id or "").strip()
        return explicit or Path(self.image_path).stem

    def pipeline_kwargs(self) -> dict[str, Any]:
        """转为 ``run_infer_pipeline`` 的关键字参数（不含 image_path/run_id/settings/arch/detector）。"""
        return {
            "phase_id": self.phase_id,
            "tract_id": self.tract_id,
            "tile_size": self.tile_size,
            "overlap_rate": self.overlap_rate,
            "chm": self.chm,
            "dsm": self.dsm,
            "dem": self.dem,
            "las": self.las,
            "las_grid_size": self.las_grid_size,
            "dem_default": self.dem_default,
            "draw_box": self.draw_box,
            "export_fmt": self.export_fmt,
        }


@dataclass
class BatchItemSummary:
    path: str
    tract_key: str
    status: str  # succeeded | failed | canceled
    run_id: str | None = None
    tract_id: str | None = None
    tree_count: int = 0
    raw_count: int = 0
    fused_count: int = 0
    report_path: str | None = None
    export_path: str | None = None
    error: str | None = None


@dataclass
class BatchSummary:
    items: list[BatchItemSummary] = field(default_factory=list)
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    canceled: int = 0
    total_trees: int = 0
    elapsed_s: float = 0.0
    cancelled: bool = False


def resolve_images(inputs: list[str]) -> list[Path]:
    """解析混合的文件/目录输入，过滤出有效后缀的影像，去重并排序。

    仅服务于 CLI 的目录展开；Web 端由前端在「加入队列」时就已把目录展开为
    逐条可编辑的待命项，后端只接受具体文件。
    """
    resolved_paths: set[Path] = set()
    for item in inputs:
        p = Path(item).expanduser()
        if not p.exists():
            log.warning("输入路径不存在: {}", item)
            continue
        if p.is_file():
            if p.suffix.lower() in _VALID_SUFFIXES:
                resolved_paths.add(p.resolve())
            else:
                log.warning("不支持的影像文件格式: {}", item)
        elif p.is_dir():
            for child in p.iterdir():
                if child.is_file() and child.suffix.lower() in _VALID_SUFFIXES:
                    resolved_paths.add(child.resolve())
    return sorted(resolved_paths)


def _build_detector_factory(settings):
    """按 arch 懒加载并缓存检测器，支持一批内混排不同模型且同一 arch 只加载一次。"""
    from ..detect import get_detector

    cache: dict[str, Any] = {}

    def factory(arch: str):
        detector = cache.get(arch)
        if detector is None:
            detector = get_detector(
                arch,
                weights=settings.get(f"detect.models.{arch}.weights", settings.get("detect.weights")),
                conf=float(settings.get("detect.conf_threshold", 0.25)),
                iou=float(settings.get("detect.iou_threshold", 0.6)),
                imgsz=int(settings.get("detect.model_input", settings.get("model_input", 1024))),
                device=settings.get("detect.device", settings.get("device", None)),
                verbose=settings.get("detect.verbose", False),
            )
            cache[arch] = detector
            log.info("批量推理加载检测器(本批内复用): arch={}", arch)
        return detector

    return factory


def run_batch_pipeline(
    items: list[BatchItemSpec],
    *,
    settings,
    cancel_run_id: str | None = None,
) -> BatchSummary:
    """串行执行一批待命项，每条使用它自己的参数。

    Args:
        items: 待命项列表，按数组顺序执行。
        settings: 已加载的 Settings。
        cancel_run_id: 顶层作业 run_id；用户终止时以它作为取消信号源。

    Returns:
        BatchSummary（包含逐条终态，供上层写入顶层 run 的 metrics）。
    """
    from .. import paths
    from ..cancellation import JobCancelled, is_cancelled, link_cancel, unlink_cancel
    from ..db import writer
    from ..utils.progress import track_progress
    from .infer import run_infer_pipeline

    t0 = time.time()
    specs = list(items)
    summary = BatchSummary(total=len(specs))

    if not specs:
        log.warning("批量推理未收到任何待命项。")
        return summary

    db_url = settings.get("url", None)
    default_arch = settings.get("detect.arch", "ultralytics")
    detector_for = _build_detector_factory(settings)

    log.info("批量推理启动：共 {} 条待命项。", len(specs))

    total = len(specs)
    idx = 0
    for spec in track_progress(specs, desc="批量影像推理"):
        idx += 1
        image_str = str(spec.image_path)
        tract_key = spec.display_tract_key

        # 已经被终止：剩下的待命项根本没开始跑，记为 canceled 且不产生 run 记录。
        if summary.cancelled or is_cancelled(cancel_run_id):
            summary.cancelled = True
            summary.canceled += 1
            summary.items.append(
                BatchItemSummary(
                    path=image_str,
                    tract_key=tract_key,
                    status=ITEM_CANCELED,
                    error="用户终止作业，该条未开始执行",
                )
            )
            log.warning("【批量调度】[{}/{}] 已终止，跳过未开始的待命项: {}", idx, total, image_str)
            continue

        arch_val = spec.arch or default_arch
        run_id = new_run_id()
        paths.set_run_context(run_id, "infer")
        # 顶层作业一旦被终止，正在跑的这一张也能在最近的检查点被夹断。
        link_cancel(run_id, cancel_run_id)

        writer.start_run_log(
            run_id,
            "infer",
            model_arch=arch_val,
            input_path=image_str,
            params={
                "arch": arch_val,
                "image": image_str,
                "phase_id": spec.phase_id,
                "tract_id": spec.tract_id,
                "tile_size": spec.tile_size,
                "overlap_rate": spec.overlap_rate,
                "export_fmt": spec.export_fmt,
            },
            parent_run_id=cancel_run_id,
            url=db_url,
        )

        item = BatchItemSummary(path=image_str, tract_key=tract_key, status=ITEM_FAILED, run_id=run_id)
        item_t0 = time.time()

        try:
            log.info("【批量调度】[{}/{}] 开始推理影像: {}", idx, total, image_str)
            res = run_infer_pipeline(
                image_str,
                run_id=run_id,
                settings=settings,
                arch=arch_val,
                detector=detector_for(arch_val),
                **spec.pipeline_kwargs(),
            )
            item.status = ITEM_SUCCEEDED
            item.tract_id = res.get("tract_id")
            item.raw_count = res.get("raw_count", 0)
            item.fused_count = res.get("fused_count", 0)
            item.tree_count = item.fused_count
            item.report_path = res.get("report_path")
            item.export_path = res.get("export_path")

            summary.succeeded += 1
            summary.total_trees += item.tree_count
            if spec.publish:
                try:
                    writer.promote_run(run_id, url=db_url)
                except Exception as promote_err:  # noqa: BLE001 - 发布失败不推翻已入库的观测
                    log.warning("批量推理发布失败，结果已入库但未激活: run_id={} {}", run_id, promote_err)
            log.info(
                "【批量调度】[{}/{}] 推理成功: {} (单图检出单木数={})",
                idx, total, image_str, item.tree_count,
            )
        except JobCancelled as exc:
            # 被夹断：这一条按失败收尾，后续未开始的统一记为已取消。
            summary.cancelled = True
            summary.failed += 1
            item.error = str(exc)
            writer.finish_run_log(
                run_id, "failed", error=str(exc), duration_s=time.time() - item_t0, url=db_url
            )
            log.warning("【批量调度】[{}/{}] 推理被用户终止，计为失败: {}", idx, total, image_str)
        except Exception as exc:  # noqa: BLE001 - 单条异常不阻断整批
            summary.failed += 1
            item.error = str(exc)
            writer.finish_run_log(
                run_id, "failed", error=str(exc), duration_s=time.time() - item_t0, url=db_url
            )
            # 沿用引擎约定: 不让日志框架 repr 推理帧中的大型 numpy 数组(C 层段错误)。
            log.opt(exception=False).error(
                "【批量调度】[{}/{}] 推理失败: {}，原因: {} — {}",
                idx, total, image_str, type(exc).__name__, exc,
            )
        finally:
            unlink_cancel(run_id)

        summary.items.append(item)
        log.info(
            "【批量进度】[{}/{}] 累计耗时: {:.1f}s | 已成功: {} | 已失败: {}\n",
            idx, total, time.time() - t0, summary.succeeded, summary.failed,
        )

    summary.elapsed_s = time.time() - t0
    log.info(
        "批量推理完成：共 {}, 成功={}, 失败={}, 已取消={}, 累计单木数={}, 耗时={:.1f}s",
        summary.total, summary.succeeded, summary.failed, summary.canceled,
        summary.total_trees, summary.elapsed_s,
    )
    return summary
