"""批量处理（阶段六）。

仅 RGB、串行执行（符合“依赖克制 + 可预测”原则）。
设计为依赖注入（DI）：source_factory / detector 可注入，便于在无 GPU/无真
实影像环境下用 mock 端到端测试整个批量编排。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..logging_setup import get_logger, new_run_id
from .runner import run_inference

log = get_logger(__name__)

# 默认可识别的 RGB 栅格后缀
DEFAULT_GLOB = "*.tif"
_RGB_SUFFIXES = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}


def discover_inputs(input_dir: str | Path, pattern: str = DEFAULT_GLOB) -> list[Path]:
    """按 glob 发现输入文件（纯函数，可单测），结果排序去重。"""
    base = Path(input_dir)
    if not base.exists():
        raise FileNotFoundError(f"输入目录不存在: {base}")
    files = sorted(
        p for p in base.glob(pattern)
        if p.is_file() and p.suffix.lower() in _RGB_SUFFIXES
    )
    return files


@dataclass
class BatchItemResult:
    path: str
    location: str
    status: str  # succeeded | failed
    tree_count: int = 0
    raw_count: int = 0
    fused_count: int = 0
    run_id: str | None = None
    tract_id: str | None = None
    error: str | None = None


@dataclass
class BatchResult:
    items: list[BatchItemResult] = field(default_factory=list)
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    elapsed_s: float = 0.0

    @property
    def total_trees(self) -> int:
        return sum(i.tree_count for i in self.items if i.status == "succeeded")


def run_batch(
    inputs: list[Path],
    detector,
    *,
    acquisition_time: str = "000000",
    source_factory: Callable[[Path], object],
    writer=None,
    persist: bool = True,
    run_kwargs: dict | None = None,
) -> BatchResult:
    """串行批量推理。

    inputs: 待处理文件列表。
    detector: 检测器实例（所有图共用，避免重复 load）。
    source_factory: path -> image_source（DI：生产用 RasterImageSource，测试用 Synthetic）。
    writer: db.writer 模块（可选，persist=True 时必传）。
    """
    run_kwargs = run_kwargs or {}
    result = BatchResult(total=len(inputs))
    t0 = time.perf_counter()
    log.info("批量开始: %d 个输入 acquisition_time=%s", len(inputs), acquisition_time)

    for idx, path in enumerate(inputs, 1):
        location = path.stem
        item = BatchItemResult(path=str(path), location=location, status="failed")
        run_id = new_run_id()
        item.run_id = run_id
        src = None
        try:
            if persist and writer is not None:
                writer.start_run_log(
                    run_id, "batch", model_arch=getattr(detector, "name", None),
                    input_path=str(path), params={"location": location},
                )
            src = source_factory(path)
            res = run_inference(src, detector, **run_kwargs)
            item.raw_count = res.raw_count
            item.fused_count = res.fused_count
            item.tree_count = len(res.detections)
            if persist and writer is not None:
                from ..geo import compute_tract_geometry

                geo = compute_tract_geometry(
                    str(path), res.meta.get("width"), res.meta.get("height"),
                    transform=getattr(src, "transform", None),
                    crs=getattr(src, "crs", None),
                ) or {}
                tract_id = writer.ensure_tract(
                    acquisition_time, location,
                    pixel_w=geo.get("pixel_w") or res.meta.get("width"),
                    pixel_h=geo.get("pixel_h") or res.meta.get("height"),
                    gsd=geo.get("gsd"),
                    geo_area=geo.get("geo_area"),
                    area_unit=geo.get("area_unit"),
                )
                item.tract_id = tract_id
                writer.write_observations(tract_id, run_id, res.detections)
                writer.finish_run_log(
                    run_id, "succeeded",
                    metrics={"raw_count": res.raw_count, "fused_count": res.fused_count},
                )
            item.status = "succeeded"
            result.succeeded += 1
            log.info("[%d/%d] %s -> %d 株", idx, len(inputs), location, item.tree_count)
        except Exception as e:  # noqa: BLE001  单图失败不中断整批
            item.error = str(e)
            result.failed += 1
            if persist and writer is not None:
                try:
                    writer.finish_run_log(run_id, "failed", error=str(e))
                except Exception:  # noqa: BLE001
                    pass
            log.exception("[%d/%d] %s 失败: %s", idx, len(inputs), location, e)
        finally:
            if src is not None and hasattr(src, "close"):
                src.close()
        result.items.append(item)

    result.elapsed_s = time.perf_counter() - t0
    log.info(
        "批量完成: 成功=%d 失败=%d 总株数=%d 耗时=%.2fs",
        result.succeeded, result.failed, result.total_trees, result.elapsed_s,
    )
    return result
