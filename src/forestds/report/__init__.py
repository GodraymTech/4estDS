"""统计报告层（阶段六）。

分层：
- metrics.py : 纯 Python 指标计算（可单测）。
- render.py  : Markdown / CSV / PNG 图表 / PDF 渲染（逐级优雅降级）。
- 本文件提供编排入口 generate_report（reader -> metrics -> render）。
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger as log
from .metrics import (
    ReportData,
    compute_report,
    density_per_hectare,
    scale_class_breakdown,
    species_composition,
)
from .render import render_charts, to_csv, to_markdown, to_pdf

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
    """按物种统计株数的纯 Python 工具。"""
    out: dict[str, int] = {}
    for s in species:
        out[s] = out.get(s, 0) + 1
    return out


def generate_report(
    *,
    tract_id: str | None = None,
    run_id: str | None = None,
    fmt: str = "md",
    out_dir: str | Path | None = None,
    with_charts: bool = True,
    db_url: str | None = None,
    vis_path: str | Path | None = None,
) -> dict:
    """端到端生成一份报告。tract_id 可传业务地块 ID 或 tract_phase_pk。"""
    from ..db import reader  # 延迟导入，避免报告指标单测耦合 db

    rid = tract_id
    if rid is None:
        raise ValueError("未找到地块：请传 --tract-id 或 tract_phase_pk")

    used_run = run_id
    if not used_run:
        used_run = reader.active_run_for_tract(rid, url=db_url)
        if not used_run:
            used_run = reader.latest_run_for_tract(rid, url=db_url)
    tract = reader.get_tract(rid, url=db_url)
    observations = reader.fetch_observations(run_id=used_run, tract_id=rid, url=db_url) \
        if used_run else reader.fetch_observations(tract_id=rid, url=db_url)
    log.info(
        "报告对象的信息: tract_id={} run_id={} 已观测单木数={}",
        rid, used_run, len(observations),
    )

    data = compute_report(observations, tract=tract, run_id=used_run)

    out_dir_p = Path(out_dir) if out_dir else Path(_default_out_dir())
    out_dir_p.mkdir(parents=True, exist_ok=True)
    stem = f"report_{rid}"

    charts: list[Path] = []
    if with_charts and fmt != "csv":
        charts = render_charts(data, out_dir_p / "reports/assets")

    result: dict = {"data": data, "charts": [str(c) for c in charts]}

    reports_dir = out_dir_p / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # 优雅压缩并将可视化检测大图放进 reports/assets 目录下，避免 PDF 文件过大
    vis_chart_p: Path | None = None
    if vis_path and Path(vis_path).exists():
        vis_dest = reports_dir / "assets/detected_visual.jpg"
        vis_dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            from PIL import Image
            with Image.open(vis_path) as img:
                w, h = img.size
                max_width = 1200
                if w > max_width:
                    h_new = int(h * (max_width / w))
                    img_resized = img.resize((max_width, h_new), Image.Resampling.LANCZOS)
                else:
                    img_resized = img
                img_resized.convert("RGB").save(str(vis_dest), "JPEG", quality=65, optimize=True)
            vis_chart_p = vis_dest
            log.info("检测框可视化大图已成功优雅压缩 -> {}", vis_dest)
        except Exception as e:
            log.warning("压缩检测可视化图失败: {}", e)

    multisource_charts: list[Path] = []
    if used_run:
        from .. import paths
        run_dir = paths.find_run_dir(used_run, "infer")
        multisource_dir = run_dir / "multisource" if run_dir else None
        if multisource_dir and multisource_dir.is_dir():
            assets_dir = reports_dir / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            for src in sorted(multisource_dir.iterdir()):
                if src.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
                    continue
                dest = assets_dir / f"multisource_{src.name}"
                try:
                    if not dest.exists() or src.stat().st_mtime > dest.stat().st_mtime:
                        try:
                            from PIL import Image

                            with Image.open(src) as img:
                                img = img.convert("RGB")
                                max_width = 1400
                                if img.width > max_width:
                                    ratio = max_width / img.width
                                    img = img.resize((max_width, int(img.height * ratio)), Image.Resampling.LANCZOS)
                                dest = dest.with_suffix(".jpg")
                                img.save(dest, "JPEG", quality=68, optimize=True)
                        except Exception:
                            dest.write_bytes(src.read_bytes())
                    multisource_charts.append(dest)
                except Exception as e:  # noqa: BLE001
                    log.warning("复制多源融合图件失败: {} -> {} ({})", src, dest, e)

    if fmt == "csv":
        out_path = reports_dir / f"{stem}.csv"
        out_path.write_text(to_csv(data), encoding="utf-8")
        result.update(format="csv", out_path=str(out_path))
    elif fmt == "pdf":
        md_text = to_markdown(
            data,
            charts=charts,
            vis_chart=vis_chart_p,
            multisource_charts=multisource_charts,
        )
        # 保存并保留 Markdown 原始报告
        md_path = reports_dir / f"{stem}.md"
        md_path.write_text(md_text, encoding="utf-8")
        
        pdf_path = reports_dir / f"{stem}.pdf"
        # 记得将 vis_chart_p 加入到 PDF 转换的图片列表，使其自动绝对化
        pdf_charts = (charts or []) + ([vis_chart_p] if vis_chart_p else [])
        out_path = to_pdf(data, pdf_path, charts=pdf_charts, md_content=md_text)
        if out_path is None:  # 优雅降级
            result.update(format="md", out_path=str(md_path), fallback="pdf->md (reportlab 缺失)")
        else:
            result.update(format="pdf", out_path=str(out_path))
    else:  # md 默认
        md_text = to_markdown(
            data,
            charts=charts,
            vis_chart=vis_chart_p,
            multisource_charts=multisource_charts,
        )
        md_path = reports_dir / f"{stem}.md"
        md_path.write_text(md_text, encoding="utf-8")
        result.update(format="md", out_path=str(md_path))

    log.info("报告已生成[{}] -> {}", result["format"], result["out_path"])
    return result


def _default_out_dir() -> Path:
    from .. import paths
    return paths.outputs_postprocess_dir()
