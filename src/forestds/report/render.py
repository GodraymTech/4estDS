"""报告渲染层（阶段六）。

三种输出，逐级优雅降级：
- Markdown / 纯文本：始终可用，零依赖。
- CSV：始终可用（标准库 csv）。
- PNG 图表：需 matplotlib，缺失则跳过并警告。
- PDF：需 reportlab，缺失则回退到 Markdown 并警告。

渲染层只消费 ReportData，不碰数据库。
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from loguru import logger as log
from .metrics import ReportData


def _fmt_dist(d: dict, unit: str = "") -> str:
    if not d or d.get("n", 0) == 0:
        return "(无数据)"
    u = unit
    return (
        f"n={d['n']} min={d['min']:.1f}{u} p10={d['p10']:.1f}{u} "
        f"median={d['median']:.1f}{u} mean={d['mean']:.1f}{u} "
        f"p90={d['p90']:.1f}{u} max={d['max']:.1f}{u} std={d['std']:.1f}{u}"
    )


def to_markdown(data: ReportData) -> str:
    """渲染为 Markdown（始终可用）。"""
    m = data.meta
    lines: list[str] = []
    lines.append("# 红树林单木检出统计报告")
    lines.append("")
    lines.append(f"- 地块: `{data.tract_id or '-'}`  位置: {m.get('location') or '-'}  "
                 f"时相: {m.get('acquisition_time') or '-'}")
    lines.append(f"- 本次 run: `{data.run_id or '-'}`")
    lines.append(f"- 影像尺寸: {m.get('pixel_w') or '?'} x {m.get('pixel_h') or '?'} px")
    lines.append("")
    lines.append("## 1. 总量与密度")
    lines.append(f"- 检出株数: **{data.tree_count}**")
    if data.density_per_ha is not None:
        lines.append(f"- 密度: **{data.density_per_ha:.1f} 株/公顷**"
                     f"（面积 {m.get('area_m2'):.0f} m²）")
    else:
        lines.append("- 密度: （地块面积未知，待仿射变换接入后补全 TODO）")
    lines.append(f"- 物种丰度: {m.get('species_richness', 0)}")
    lines.append("")
    lines.append("## 2. 物种组成")
    if data.species:
        for sp, cnt in data.species.items():
            ratio = cnt / data.tree_count if data.tree_count else 0
            lines.append(f"- {sp}: {cnt} ({ratio:.1%})")
    else:
        lines.append("- (无)")
    lines.append("")
    lines.append("## 3. 冠幅与尺寸分布（像素）")
    lines.append(f"- 冠幅宽: {_fmt_dist(data.crown_w_px, 'px')}")
    lines.append(f"- 冠幅高: {_fmt_dist(data.crown_h_px, 'px')}")
    lines.append(f"- 冠幅面积: {_fmt_dist(data.crown_area_px, 'px²')}")
    lines.append("")
    lines.append("## 4. 置信度与树高")
    lines.append(f"- 置信度: {_fmt_dist(data.confidence)}")
    lines.append(f"- 树高: {_fmt_dist(data.height, 'm')}")
    lines.append("")
    lines.append("## 5. 离散尺度档占比（创新点 A）")
    if data.scale_classes:
        for ss, info in data.scale_classes.items():
            lines.append(f"- 切片边长 {ss}px: {info['count']} 株 ({info['ratio']:.1%})")
    else:
        lines.append("- (无)")
    lines.append("")
    return "\n".join(lines)


def to_csv(data: ReportData) -> str:
    """渲染为单表 CSV（指标 -> 值，标准库）。"""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["metric", "value"])
    w.writerow(["tract_id", data.tract_id or ""])
    w.writerow(["run_id", data.run_id or ""])
    w.writerow(["tree_count", data.tree_count])
    w.writerow(["density_per_ha", "" if data.density_per_ha is None else f"{data.density_per_ha:.3f}"])
    w.writerow(["species_richness", data.meta.get("species_richness", 0)])
    for sp, cnt in data.species.items():
        w.writerow([f"species:{sp}", cnt])
    for label, dist in (("crown_w_px", data.crown_w_px), ("crown_h_px", data.crown_h_px),
                        ("crown_area_px", data.crown_area_px), ("confidence", data.confidence),
                        ("height", data.height)):
        for stat in ("n", "min", "median", "mean", "p90", "max", "std"):
            if stat in dist:
                w.writerow([f"{label}.{stat}", dist[stat]])
    for ss, info in data.scale_classes.items():
        w.writerow([f"scale:{ss}px.count", info["count"]])
        w.writerow([f"scale:{ss}px.ratio", f"{info['ratio']:.4f}"])
    return buf.getvalue()


def render_charts(data: ReportData, out_dir: Path) -> list[Path]:
    """生成 PNG 图表（需 matplotlib）。缺依赖则返回空列表并警告。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:  # noqa: BLE001
        log.warning("matplotlib 不可用，跳过图表: %s", e)
        return []

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    produced: list[Path] = []

    # 物种组成柱状图
    if data.species:
        fig, ax = plt.subplots(figsize=(6, 3.5))
        ax.bar(list(data.species.keys()), list(data.species.values()), color="#2e7d32")
        ax.set_title("Species composition")
        ax.set_ylabel("count")
        fig.tight_layout()
        p = out_dir / "species.png"
        fig.savefig(p, dpi=120)
        plt.close(fig)
        produced.append(p)

    # 离散尺度档占比饼图
    if data.scale_classes:
        fig, ax = plt.subplots(figsize=(4.5, 4.5))
        labels = [f"{k}px" for k in data.scale_classes]
        sizes = [v["count"] for v in data.scale_classes.values()]
        ax.pie(sizes, labels=labels, autopct="%1.1f%%", startangle=90)
        ax.set_title("Scale-class share")
        fig.tight_layout()
        p = out_dir / "scale_classes.png"
        fig.savefig(p, dpi=120)
        plt.close(fig)
        produced.append(p)

    log.info("生成图表 %d 张 -> %s", len(produced), out_dir)
    return produced


def to_pdf(data: ReportData, out_path: Path, *, charts: list[Path] | None = None) -> Path | None:
    """生成 PDF（需 reportlab）。缺依赖则返回 None 并警告，由调用方回退 Markdown。"""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.pdfgen import canvas
    except Exception as e:  # noqa: BLE001
        log.warning("reportlab 不可用，无法生成 PDF: %s", e)
        return None

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(out_path), pagesize=A4)
    width, height = A4
    y = height - 2 * cm

    def line(text: str, size: int = 11, dy: float = 0.7 * cm) -> None:
        nonlocal y
        if y < 2 * cm:
            c.showPage()
            y = height - 2 * cm
        c.setFont("Helvetica", size)
        c.drawString(2 * cm, y, text)
        y -= dy

    line("4estDS Tree Detection Report", size=16, dy=1.0 * cm)
    line(f"tract={data.tract_id or '-'}  run={data.run_id or '-'}", size=9)
    line(f"location={data.meta.get('location') or '-'}  time={data.meta.get('acquisition_time') or '-'}", size=9)
    line("")
    line(f"Tree count: {data.tree_count}", size=12)
    if data.density_per_ha is not None:
        line(f"Density: {data.density_per_ha:.1f} /ha", size=12)
    line(f"Species richness: {data.meta.get('species_richness', 0)}", size=12)
    line("")
    line("Species composition:", size=12)
    for sp, cnt in data.species.items():
        line(f"  - {sp}: {cnt}", size=10)
    line("")
    cw = data.crown_w_px
    if cw.get("n"):
        line(f"Crown width px: median={cw['median']:.1f} p90={cw['p90']:.1f} max={cw['max']:.1f}", size=10)
    conf = data.confidence
    if conf.get("n"):
        line(f"Confidence: median={conf['median']:.2f} min={conf['min']:.2f}", size=10)

    for chart in (charts or []):
        try:
            from reportlab.lib.utils import ImageReader
            img = ImageReader(str(chart))
            iw, ih = img.getSize()
            disp_w = min(width - 4 * cm, 12 * cm)
            disp_h = disp_w * ih / iw
            if y - disp_h < 2 * cm:
                c.showPage()
                y = height - 2 * cm
            c.drawImage(img, 2 * cm, y - disp_h, width=disp_w, height=disp_h)
            y -= disp_h + 0.5 * cm
        except Exception as e:  # noqa: BLE001
            log.warning("PDF 嵌入图表失败 %s: %s", chart, e)

    c.showPage()
    c.save()
    log.info("生成 PDF -> %s", out_path)
    return out_path
