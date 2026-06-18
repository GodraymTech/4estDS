"""统计报告层（阶段六）。

分层：
- metrics.py : 纯 Python 指标计算（可单测）。
- render.py  : Markdown / CSV / PNG 图表 / PDF 渲染（逐级优雅降级）。
- 本文件提供编排入口 generate_report（reader -> metrics -> render）。
"""
from __future__ import annotations

from pathlib import Path

from ..logging_setup import get_logger
from .metrics import (
    ReportData,
    compute_report,
    density_per_hectare,
    scale_class_breakdown,
    species_composition,
)
from .render import render_charts, to_csv, to_markdown, to_pdf

log = get_logger(__name__)

__all__ = [
    "ReportData",
    "compute_report",
    "density_per_hectare",
    "scale_class_breakdown",
    "species_composition",
    "summarize_counts",
    "render_charts",
    "to_csv",
    "to_markdown",
    "to_pdf",
    "generate_report",
]


def summarize_counts(species: list[str]) -> dict[str, int]:
    """按物种统计株数（向后兼容的纯 Python 工具）。"""
    out: dict[str, int] = {}
    for s in species:
        out[s] = out.get(s, 0) + 1
    return out


def generate_report(
    *,
    tract_id: str | None = None,
    run_id: str | None = None,
    acquisition_time: str | None = None,
    location: str | None = None,
    fmt: str = "md",
    out_dir: str | Path | None = None,
    with_charts: bool = True,
    db_url: str | None = None,
) -> dict:
    """端到端生成一份报告。

    定位优先级: tract_id > (acquisition_time, location)。run_id 可选限定某次 run。
    fmt: 'md' | 'csv' | 'pdf'。pdf 缺 reportlab 时自动回退到 md。
    返回 {'format', 'out_path', 'data', 'charts', 'fallback'?}。
    """
    from ..db import reader  # 延迟导入，避免报告指标单测耦合 db

    rid = reader.resolve_tract_id(
        tract_id=tract_id, acquisition_time=acquisition_time,
        location=location, url=db_url,
    )
    if rid is None:
        raise ValueError("未找到地块：请传 --tract-id 或 (--acquisition-time 与 --location)")

    used_run = run_id or reader.latest_run_for_tract(rid, url=db_url)
    tract = reader.get_tract(rid, url=db_url)
    observations = reader.fetch_observations(run_id=used_run, tract_id=rid, url=db_url) \
        if used_run else reader.fetch_observations(tract_id=rid, url=db_url)
    log.info(
        "报告数据: tract_id=%s run_id=%s 观测=%d 条",
        rid, used_run, len(observations),
    )

    data = compute_report(observations, tract=tract, run_id=used_run)

    out_dir_p = Path(out_dir) if out_dir else Path(_default_out_dir())
    out_dir_p.mkdir(parents=True, exist_ok=True)
    stem = f"report_{rid}"

    charts: list[Path] = []
    if with_charts and fmt in ("pdf",):
        charts = render_charts(data, out_dir_p / f"{stem}_charts")

    result: dict = {"data": data, "charts": [str(c) for c in charts]}

    if fmt == "csv":
        out_path = out_dir_p / f"{stem}.csv"
        out_path.write_text(to_csv(data), encoding="utf-8")
        result.update(format="csv", out_path=str(out_path))
    elif fmt == "pdf":
        out_path = to_pdf(data, out_dir_p / f"{stem}.pdf", charts=charts)
        if out_path is None:  # 优雅降级
            md_path = out_dir_p / f"{stem}.md"
            md_path.write_text(to_markdown(data), encoding="utf-8")
            result.update(format="md", out_path=str(md_path), fallback="pdf->md (reportlab 缺失)")
        else:
            result.update(format="pdf", out_path=str(out_path))
    else:  # md 默认
        out_path = out_dir_p / f"{stem}.md"
        out_path.write_text(to_markdown(data), encoding="utf-8")
        result.update(format="md", out_path=str(out_path))

    log.info("报告已生成[%s] -> %s", result["format"], result["out_path"])
    return result


def _default_out_dir() -> Path:
    from .. import paths
    return paths.outputs_dir()
