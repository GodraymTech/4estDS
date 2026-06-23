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


def _format_table_row(label: str, d: dict, unit: str = "") -> str:
    if not d or d.get("n", 0) == 0:
        return f"| {label} | 0 | - | - | - | - | - | - | - |"
    u = unit
    return (
        f"| {label} | {d['n']} | {d['min']:.2f}{u} | {d['p10']:.2f}{u} | "
        f"{d['median']:.2f}{u} | {d['mean']:.2f}{u} | {d['p90']:.2f}{u} | "
        f"{d['max']:.2f}{u} | {d['std']:.2f}{u} |"
    )


def to_markdown(data: ReportData, charts: list[str | Path] | None = None, vis_chart: Path | None = None) -> str:
    """将报告数据渲染为高标准排版的 Markdown 文本。"""
    m = data.meta
    lines: list[str] = []
    
    # 查找特定图表的辅助闭包，以便在学术文本段落中精准插入
    def get_chart_md(filename: str, caption: str) -> str:
        if not charts:
            return ""
        for c in charts:
            p = Path(c)
            if p.name == filename:
                return f"\n![{caption}](./assets/{p.name})\n"
        return ""

    lines.append("# 红树林AI检测统计报告")
    lines.append("")
    lines.append("---")
    lines.append(f"- **地块 (Tract)**: `{data.tract_id or '-'}`  **位置 (Location)**: {m.get('location') or '-'}  "
                 f"**观测时相 (Time)**: {m.get('acquisition_time') or '-'}")
    lines.append(f"- **分析运行编号 (Run ID)**: `{data.run_id or '-'}`")
    lines.append(f"- **影像分辨率 (Dimensions)**: {m.get('pixel_w') or '?'} x {m.get('pixel_h') or '?'} 像素")
    lines.append("---")
    lines.append("")
    
    # ------------------ 一、 整体林木群落结构分析 (Community Structure & Canopy Closure) ------------------
    lines.append("## 一、 整体林木群落结构分析 (Community Structure & Canopy Closure)")
    lines.append("")
    lines.append("### 1.1 群落物种组成与盖度主导率")
    lines.append("森林群落的多样性与空间分布占领度通常通过**株数相对多度 (Relative Abundance, RA)** 和 **投影相对盖度 (Relative Cover, RC)** 双维度来量化。相对多度反映了各树种在个体数量上的占比，而相对盖度则揭示了其在冠层投影面积（水平生态空间）上的主导地位。本测区物种多度与盖度主导率对比图如下：")
    lines.append("")
    
    # 穿插群落饼图和盖度圆环图
    composition_md = get_chart_md("species_composition.png", "树种多度群落组成构成 (Species Abundance Pie)")
    dominance_md = get_chart_md("species_dominance.png", "树种空间投影盖度占比 (Species Canopy Cover Donut)")
    if composition_md:
        lines.append(composition_md)
    if dominance_md:
        lines.append(dominance_md)
        
    lines.append("")
    lines.append("> [!NOTE]")
    lines.append("> **多度与盖度对比解读**：当相对盖度 (RC) 显著高于相对多度 (RA) 时，表明该树种个体发育充分，树冠冠幅较大，是群落中的强势建群种；反之，若多度高但盖度极小，则表明处于幼苗或林下层受压制状态。本测区数据清晰反映了各物种的空间竞争演潜水平。")
    lines.append("")
    
    lines.append("### 1.2 林分密度与林冠郁闭度评估")
    lines.append(f"- **林木检出总株数 (Tree Count)**: **{data.tree_count}** 株")
    if data.density_per_ha is not None:
        lines.append(f"- **整体林分密度 (Density)**: **{data.density_per_ha:.1f} 株/公顷**"
                     f"（有效覆盖面积 {m.get('area_m2'):.0f} m²）")
    else:
        lines.append("- **整体林分密度**: （有效覆盖面积未知，待仿射投影对齐接入）")
        
    cc = m.get("canopy_cover_rate")
    if cc is not None:
        if cc < 0.2:
            cc_desc = "极度稀疏林 (Sparse Canopy)"
            cc_advice = "该地块郁闭度较低，林地仍有大量裸露空地，适宜开展补植补造，增强群落稳固性。"
        elif cc < 0.4:
            cc_desc = "疏林群落 (Open Canopy)"
            cc_advice = "群落呈斑块状零星分布，处于生态恢复和郁闭过渡期，需防范风浪冲刷破坏幼树结构。"
        elif cc < 0.7:
            cc_desc = "中度郁闭林 (Moderately Closed)"
            cc_advice = "林木冠层已经部分连片郁闭，防风消浪和固碳储能量已开始显现显著生态效益。"
        else:
            cc_desc = "密林群落 (Closed Canopy)"
            cc_advice = "郁闭度极高，处于老龄熟林阶段。应防范种内生态位过度竞争，可适当进行生态抚育调控。"
            
        lines.append(f"- **测区林冠郁闭度 (Canopy Cover)**: **{cc:.1%}** ({cc_desc})，总树冠投影面积为 **{m.get('total_crown_area', 0.0):.1f} m²**")
        lines.append("")
        lines.append(f"> [!IMPORTANT]")
        lines.append(f"> **林相科学评价**：测区林冠郁闭度经测定为 **{cc:.1%}**。依据林学分类判定为 **{cc_desc}**。{cc_advice}")
    else:
        lines.append("- **测区林冠郁闭度**: （有效地理覆盖面积未知，暂未估算）")
    lines.append(f"- **识别物种丰度 (Species Richness)**: {m.get('species_richness', 0)} 类")
    lines.append("")
    
    # ------------------ 二、 单木特征多维度统计与垂直结构分层 (Features & Stratification) ------------------
    lines.append("## 二、 单木特征多维度统计与垂直结构分层 (Features & Stratification)")
    lines.append("")
    lines.append("### 2.1 整体特征多维描述表")
    lines.append("本模块对测区内所有检出单木的多维物理及解译指标进行全量数理统计，全面透视林区的数量水平、离散程度与形态分布范围：")
    lines.append("")
    lines.append("| 观测指标维度 (Metric Dimension) | 样本数 (n) | 最小值 (min) | 10%分位数 (p10) | 中位数 (median) | 平均值 (mean) | 90%分位数 (p90) | 最大值 (max) | 标准差 (std) |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    
    lines.append(_format_table_row("检测置信度 (Confidence)", data.confidence))
    lines.append(_format_table_row("林木估计树高 (Height, m)", data.height))
    lines.append(_format_table_row("树冠三维体积 (Volume, m³)", data.crown_volume_geo))
    lines.append(_format_table_row("像素冠幅宽 (Crown W, px)", data.crown_w_px))
    lines.append(_format_table_row("像素冠幅高 (Crown H, px)", data.crown_h_px))
    lines.append(_format_table_row("像素冠幅面积 (Crown Area, px²)", data.crown_area_px))
    lines.append(_format_table_row("物理树冠宽 (Crown W, m)", data.crown_w_geo))
    lines.append(_format_table_row("物理树冠高 (Crown H, m)", data.crown_h_geo))
    lines.append(_format_table_row("物理树冠面积 (Crown Area, m²)", data.crown_area_geo))
    lines.append("")

    lines.append("### 2.2 垂直林冠层三维高度与体积分布特征")
    lines.append("高度和体积是森林垂直空间异质性的表征。树高的垂直分布展示了冠层的分层状况（如灌木层、小乔木层、大乔木层），而树冠三维体积则从立体几何角度反映了绿色森林资源的积蓄大小。以下为单木估计高度与树冠三维体积的频率直方图与高斯核密度（KDE）拟合线：")
    lines.append("")
    
    # 穿插高度和体积频率直方图
    height_dist_md = get_chart_md("height_distribution.png", "单木高度频率分布直方与核密度拟合 (Tree Height Distribution)")
    volume_dist_md = get_chart_md("volume_distribution.png", "单木树冠三维体积分布直方与核密度拟合 (Tree Volume Distribution)")
    if height_dist_md:
        lines.append(height_dist_md)
    if volume_dist_md:
        lines.append(volume_dist_md)
        
    lines.append("")
    lines.append("> [!TIP]")
    lines.append("> **分布图谱的林学意义**：如果高度分布曲线呈现明显的单峰左偏，表明群落由大量中幼林构成，正处于快速的恢复演替中；若呈现明显的双峰或多峰，表明测区垂直分层明显，已经具备了较为成熟的复层林相结构。体积分布直方图则直接体现了森林立体三维空间的占领程度。")
    lines.append("")

    # ------------------ 三、 生态尺度异异速生长分析 (Allometric Scaling & Correlations) ------------------
    lines.append("## 三、 生态尺度异速生长分析 (Allometric Scaling & Correlations)")
    lines.append("")
    lines.append("### 3.1 树高与冠幅二维面积的线性演变关联")
    lines.append("在森林生态系统中，树高与冠幅的协调增长展示了单木从“水平争光拓展”向“垂直向上竞争”的演化历程。以下为树高与树冠投影面积的一元线性回归回归散点图：")
    lines.append("")
    
    # 穿插树高与冠幅面积关联回归图
    correlation_md = get_chart_md("height_area_correlation.png", "树高与树冠投影面积一元线性回归拟合 (Height vs. Area)")
    if correlation_md:
        lines.append(correlation_md)
        
    lines.append("")
    lines.append("### 3.2 树冠面积与体积的异速比例生长规律")
    lines.append("异速生长理论（Allometric Scaling）指出，单木的水平投影面积 (A) 与三维立体体积 (V) 通常服从非线性的幂律异速生长方程：V = a * A^b。我们利用双对数线性变换拟合该生态学指数，以揭示红树林在空间维度上的扩展速率机制。拟合曲线如下：")
    lines.append("")
    
    # 穿插异速生长回归拟合图
    powerlaw_md = get_chart_md("area_volume_powerlaw.png", "面积与体积生态异速生长幂律回归拟合 (Canopy Area vs. Volume)")
    if powerlaw_md:
        lines.append(powerlaw_md)
        
    lines.append("")
    lines.append("> [!NOTE]")
    lines.append("> **生态异速指数 b 的物理解读**：拟合判定系数 R^2 越高，表明单木的物理外形生长一致性越强。回归方程中的幂指数 b 若接近 1.5，说明红树林的生长呈标准的各项同性空间膨胀；若 b < 1.0，表明生长更加倾向于水平冠幅的横向扩张以抢夺阳光；若 b > 1.5，则反映测区在垂直方向的树高生长极具优势。")
    lines.append("")

    # ------------------ 四、 树种空间生长异质性对比 (Species Heterogeneity) ------------------
    lines.append("## 四、 树种空间生长异质性对比 (Species Heterogeneity)")
    lines.append("")
    lines.append("### 4.1 树种基本生态形态特征对比")
    lines.append("通过对不同树种的株数、平均高度、最大高度、平均体积和平均冠幅进行细分统计，量化不同树种的生态发育状态：")
    lines.append("")
    
    sp_analysis = m.get("species_analysis")
    if sp_analysis:
        lines.append("| 树种 (Species) | 株数 (Count) | 占比 (Ratio) | 平均树高 (Avg H) | 最大树高 (Max H) | 平均体积 (Avg Vol) | 平均冠幅 (Avg Area) |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for sp, stats in sp_analysis.items():
            ratio_str = f"{stats['ratio']:.1%}"
            avg_h = f"{stats['avg_height']:.2f} m" if stats['avg_height'] is not None else "-"
            max_h = f"{stats['max_height']:.2f} m" if stats['max_height'] is not None else "-"
            avg_v = f"{stats['avg_volume']:.2f} m³" if stats['avg_volume'] is not None else "-"
            avg_a = f"{stats['avg_crown_area']:.2f} m²" if stats['avg_crown_area'] is not None else "-"
            lines.append(f"| **{sp}** | {stats['count']} | {ratio_str} | {avg_h} | {max_h} | {avg_v} | {avg_a} |")
    else:
        lines.append("- (无物种级交叉分析数据)")
    lines.append("")

    lines.append("### 4.2 树种优势度与物种重要值 (IV) 综合评估")
    lines.append("在群落生态调查中，物种重要值 (Importance Value, IV) 是衡量某个物种在群落中生态地位的综合决策指标。它兼顾了树木个体的**多度占比（RA）**和在物理投影面积上的**盖度占比（RC）**：")
    lines.append("")
    if sp_analysis:
        lines.append("| 树种 (Species) | 株数 (Count) | 相对多度 (RA) | 相对盖度 (RC) | 重要值 (IV) | 总树冠体积 (m³) | 冠层饱满度 (FI) |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for sp, stats in sp_analysis.items():
            ra_str = f"{stats['ra']:.1%}"
            rc_str = f"{stats['rc']:.1%}"
            iv_str = f"{stats['iv']:.1%}"
            tot_v = f"{stats['total_volume']:.1f} m³"
            fi_val = f"{stats['fi']:.2f}" if stats['fi'] is not None else "-"
            lines.append(f"| **{sp}** | {stats['count']} | {ra_str} | {rc_str} | {iv_str} | {tot_v} | {fi_val} |")
    else:
        lines.append("- (无物种级优势度数据)")
    lines.append("")

    # 4.3 树种空间生长异质性对比图表
    # 如果 charts 里面有箱线图，则绘制
    h_box_md = get_chart_md("species_height_comparison.png", "各树种单木高度生长差异对比箱线图 (Tree Height Boxplot)")
    a_box_md = get_chart_md("species_area_comparison.png", "各树种单木投影面积差异对比箱线图 (Crown Area Boxplot)")
    if h_box_md or a_box_md:
        lines.append("### 4.3 树种空间生长异质性对比图表")
        lines.append("利用箱线图多维对比不同物种的垂直树高与水平二维冠幅面积的总体分布区间、中位水平及离群值状态，量化生态竞争分化：")
        lines.append("")
        if h_box_md:
            lines.append(h_box_md)
        if a_box_md:
            lines.append(a_box_md)

    # ------------------ 五、 目标检测多尺度解译 (Multi-scale Analysis) ------------------
    lines.append("## 五、 目标检测多尺度解译 (Multi-scale Analysis)")
    lines.append("")
    lines.append("基于创新的四叉树在线自适应尺寸匹配（SCOPE）模型，统计不同图像切割边长（slice_size）对单木的识别贡献率，验证本算法的多尺度可解释性：")
    lines.append("")
    if data.scale_classes:
        for ss, info in data.scale_classes.items():
            lines.append(f"- **切片分幅边长 {ss}px**: {info['count']} 株，检出占比 **{info['ratio']:.1%}**")
    else:
        lines.append("- (未获取多尺度切片统计)")
    lines.append("")
    
    # ------------------ 六、 测区树木检测空间分布可视化图 ------------------
    if vis_chart:
        lines.append("## 六、 测区树木检测空间分布可视化图 (Canopy Detection Visualization)")
        lines.append("")
        lines.append("为了直观呈现林木的密集程度与个体形态差异，系统将最终去重去偏后的单木空间定位与检测框绘制渲染回原正射影像。下图为该测区去重合并后的核心检出分布图（已进行大图无损压缩以优化排版）：")
        lines.append("")
        lines.append(f"\n![单木空间分布检出可视化图](./assets/{vis_chart.name})\n")
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
                        ("crown_area_px", data.crown_area_px),
                        ("crown_w_geo", data.crown_w_geo), ("crown_h_geo", data.crown_h_geo),
                        ("crown_area_geo", data.crown_area_geo),
                        ("confidence", data.confidence), ("height", data.height),
                        ("crown_volume_geo", data.crown_volume_geo)):
        for stat in ("n", "min", "median", "mean", "p90", "max", "std"):
            if stat in dist:
                w.writerow([f"{label}.{stat}", dist[stat]])
    for ss, info in data.scale_classes.items():
        w.writerow([f"scale:{ss}px.count", info["count"]])
        w.writerow([f"scale:{ss}px.ratio", f"{info['ratio']:.4f}"])
    return buf.getvalue()


def render_charts(data: ReportData, out_dir: Path) -> list[Path]:
    """生成 PNG 图表（需 matplotlib 与 numpy）。缺依赖则返回空列表并警告。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception as e:
        log.warning("matplotlib 或 numpy 不可用，跳过图表生成: {}", e)
        return []

    # 动态检测系统支持的中文字体，优先保障 Linux/WSL 等环境中的中文渲染
    from matplotlib.font_manager import fontManager
    font_candidates = [
        'WenQuanYi Micro Hei', 
        'Noto Sans CJK SC', 
        'Noto Sans CJK JP',
        'Droid Sans Fallback', 
        'SimHei', 
        'SimSun', 
        'Microsoft YaHei'
    ]
    found_fonts = [f.name for f in fontManager.ttflist if f.name in font_candidates]
    # 将 DejaVu Sans 放在最前面，使其成为英文字符与数字渲染的基准，中文则自动向下 fallback 到中文字体
    plt.rcParams['font.sans-serif'] = ['DejaVu Sans'] + found_fonts + font_candidates
    plt.rcParams['axes.unicode_minus'] = False
    
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    produced: list[Path] = []
    
    m = data.meta
    raw_obs = m.get("raw_observations", [])
    COLORS = ["#2e7d32", "#1976d2", "#e64a19", "#7b1fa2", "#fbc02d", "#00796b"]

    # 1. 树种群落构成饼图
    if data.species:
        fig, ax = plt.subplots(figsize=(6, 5))
        labels = list(data.species.keys())
        sizes = list(data.species.values())
        explode = [0.05 if (v / sum(sizes)) < 0.05 else 0 for v in sizes]
        
        wedges, texts, autotexts = ax.pie(
            sizes, explode=explode, labels=labels, autopct="%1.1f%%",
            startangle=140, colors=COLORS[:len(labels)], shadow=False,
            textprops=dict(color="black", fontsize=10)
        )
        for autotext in autotexts:
            autotext.set_fontweight('bold')
        
        ax.set_title("Species Abundance Composition", fontsize=12, fontweight='bold', pad=15)
        fig.tight_layout()
        p = out_dir / "species_composition.png"
        fig.savefig(p, dpi=150)
        plt.close(fig)
        produced.append(p)

    # 2. 树种相对盖度圆环图 (Donut Chart)
    if data.species:
        sp_names = []
        sp_rcs = []
        sp_analysis = m.get("species_analysis", {})
        for sp in data.species.keys():
            if sp in sp_analysis:
                sp_names.append(sp)
                sp_rcs.append(sp_analysis[sp]["rc"])
        
        if sum(sp_rcs) > 0:
            fig, ax = plt.subplots(figsize=(6, 5))
            wedges, texts, autotexts = ax.pie(
                sp_rcs, labels=sp_names, autopct="%1.1f%%",
                startangle=140, colors=COLORS[:len(sp_names)],
                pctdistance=0.75,
                wedgeprops=dict(width=0.4, edgecolor='w', linewidth=2)
            )
            for autotext in autotexts:
                autotext.set_fontweight('bold')
            ax.set_title("Species Canopy Cover Dominance", fontsize=11, fontweight='bold', pad=15)
            fig.tight_layout()
            p = out_dir / "species_dominance.png"
            fig.savefig(p, dpi=150)
            plt.close(fig)
            produced.append(p)

    # 3. 独立的树高分布直方与 KDE 拟合图
    heights = [o["height"] for o in raw_obs if o.get("height") is not None]
    valid_h = [h for h in heights if not np.isnan(h)]
    if valid_h:
        fig, ax = plt.subplots(figsize=(7, 4.5))
        counts, bins, _ = ax.hist(valid_h, bins=15, color="#4caf50", edgecolor="#2e7d32", alpha=0.7, rwidth=0.85, density=True)
        if len(valid_h) > 1:
            try:
                from scipy.stats import gaussian_kde
                kde = gaussian_kde(valid_h)
                x_grid = np.linspace(min(valid_h), max(valid_h), 200)
                ax.plot(x_grid, kde(x_grid), color="#1b5e20", linewidth=2, label="KDE Density")
                ax.legend(frameon=True, fontsize=9)
            except Exception:
                pass
        ax.set_title("Tree Height Distribution", fontsize=11, fontweight='bold', pad=12)
        ax.set_xlabel("Height (m)", fontsize=10)
        ax.set_ylabel("Density", fontsize=10)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.grid(True, linestyle='--', alpha=0.5, color='#e0e0e0')
        fig.tight_layout()
        p = out_dir / "height_distribution.png"
        fig.savefig(p, dpi=150)
        plt.close(fig)
        produced.append(p)

    # 4. 独立的树冠体积分布直方与 KDE 拟合图
    volumes = [o["volume"] for o in raw_obs if o.get("volume") is not None]
    valid_v = [v for v in volumes if not np.isnan(v)]
    if valid_v:
        fig, ax = plt.subplots(figsize=(7, 4.5))
        counts, bins, _ = ax.hist(valid_v, bins=15, color="#2196f3", edgecolor="#1976d2", alpha=0.7, rwidth=0.85, density=True)
        if len(valid_v) > 1:
            try:
                from scipy.stats import gaussian_kde
                kde = gaussian_kde(valid_v)
                x_grid = np.linspace(min(valid_v), max(valid_v), 200)
                ax.plot(x_grid, kde(x_grid), color="#0d47a1", linewidth=2, label="KDE Density")
                ax.legend(frameon=True, fontsize=9)
            except Exception:
                pass
        ax.set_title("Tree Volume Distribution", fontsize=11, fontweight='bold', pad=12)
        ax.set_xlabel("Volume (m^3)", fontsize=10)
        ax.set_ylabel("Density", fontsize=10)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.grid(True, linestyle='--', alpha=0.5, color='#e0e0e0')
        fig.tight_layout()
        p = out_dir / "volume_distribution.png"
        fig.savefig(p, dpi=150)
        plt.close(fig)
        produced.append(p)

    # 5. 单木高度与树冠面积关联拟合散点图
    scatter_data = [(o["height"], o["crown_area"]) for o in raw_obs if o.get("height") is not None and o.get("crown_area") is not None]
    if len(scatter_data) > 5:
        fig, ax = plt.subplots(figsize=(7, 5))
        xs = np.array([pt[0] for pt in scatter_data])
        ys = np.array([pt[1] for pt in scatter_data])
        
        ax.scatter(xs, ys, color="#e64a19", alpha=0.6, edgecolors='none', s=25, label="Observed Trees")
        
        try:
             slope, intercept = np.polyfit(xs, ys, 1)
             x_line = np.linspace(min(xs), max(xs), 100)
             y_line = slope * x_line + intercept
             
             y_pred = slope * xs + intercept
             ss_tot = np.sum((ys - np.mean(ys)) ** 2)
             ss_res = np.sum((ys - y_pred) ** 2)
             r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0
             
             label_text = f"Linear Fit: y = {slope:.2f}x + {intercept:.2f} (R^2 = {r_squared:.3f})"
             ax.plot(x_line, y_line, color="#d84315", linestyle="-", linewidth=2, label=label_text)
        except Exception as poly_err:
             log.warning("拟合回归线失败: {}", poly_err)
            
        ax.set_title("Height vs. Crown Area Correlation", fontsize=11, fontweight='bold', pad=10)
        ax.set_xlabel("Height (m)", fontsize=10)
        ax.set_ylabel("Crown Area (m^2)", fontsize=10)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.grid(True, linestyle='--', alpha=0.5, color='#e0e0e0')
        ax.legend(frameon=True, facecolor='white', edgecolor='#e0e0e0', loc="upper left", fontsize=9)
        
        fig.tight_layout()
        p = out_dir / "height_area_correlation.png"
        fig.savefig(p, dpi=150)
        plt.close(fig)
        produced.append(p)

    # 6. 树冠面积与体积生态异速生长 (Allometric Scaling) 幂律拟合图
    allometric_data = [
        (o["crown_area"], o["volume"]) 
        for o in raw_obs 
        if o.get("crown_area") is not None and o.get("volume") is not None and o["crown_area"] > 0 and o["volume"] > 0
    ]
    if len(allometric_data) > 5:
        fig, ax = plt.subplots(figsize=(7, 5))
        areas = np.array([pt[0] for pt in allometric_data])
        vols = np.array([pt[1] for pt in allometric_data])
        
        ax.scatter(areas, vols, color="#4a148c", alpha=0.6, edgecolors='none', s=25, label="Observed Points")
        
        try:
            log_x = np.log(areas)
            log_y = np.log(vols)
            slope, intercept = np.polyfit(log_x, log_y, 1) 
            a = np.exp(intercept)
            b = slope
            
            x_line = np.linspace(min(areas), max(areas), 100)
            y_line = a * (x_line ** b)
            
            y_pred = slope * log_x + intercept
            ss_tot = np.sum((log_y - np.mean(log_y)) ** 2)
            ss_res = np.sum((log_y - y_pred) ** 2)
            r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0
            
            label_text = f"Allometric Fit: V = {a:.3f} * A^{b:.2f} (R^2 = {r_squared:.3f})"
            ax.plot(x_line, y_line, color="#8e24aa", linestyle="-", linewidth=2, label=label_text)
        except Exception as power_err:
            log.warning("异速生长幂律拟合失败: {}", power_err)
            
        ax.set_title("Canopy Area vs. Volume Allometric Scaling", fontsize=11, fontweight='bold', pad=10)
        ax.set_xlabel("Crown Area (m^2)", fontsize=10)
        ax.set_ylabel("Volume (m^3)", fontsize=10)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.grid(True, linestyle='--', alpha=0.5, color='#e0e0e0')
        ax.legend(frameon=True, facecolor='white', edgecolor='#e0e0e0', loc="upper left", fontsize=9)
        
        fig.tight_layout()
        p = out_dir / "area_volume_powerlaw.png"
        fig.savefig(p, dpi=150)
        plt.close(fig)
        produced.append(p)

    # 7. 各树种树高生长差异箱线图
    sp_names = list(data.species.keys())
    if len(sp_names) > 1:
        sp_groups = []
        labels = []
        for sp in sp_names:
            grp = [o["height"] for o in raw_obs if o.get("species") == sp and o.get("height") is not None]
            if len(grp) >= 3:
                sp_groups.append(grp)
                labels.append(sp)
                
        if len(sp_groups) > 1:
            fig, ax = plt.subplots(figsize=(7, 4.8))
            box = ax.boxplot(
                sp_groups, patch_artist=True,
                showmeans=True, showfliers=True,
                boxprops=dict(facecolor="#e0f2f1", color="#00796b", linewidth=1.2),
                capprops=dict(color="#00796b", linewidth=1.2),
                whiskerprops=dict(color="#00796b", linestyle="--", linewidth=1.2),
                flierprops=dict(marker='o', markerfacecolor='#e57373', markersize=4, markeredgecolor='none'),
                medianprops=dict(color="#d84315", linewidth=1.5),
                meanprops=dict(marker='^', markerfacecolor='#1976d2', markeredgecolor='none', markersize=5)
            )
            ax.set_xticks(range(1, len(labels) + 1))
            ax.set_xticklabels(labels)
            
            for i, patch in enumerate(box['boxes']):
                patch.set_facecolor(COLORS[i % len(COLORS)])
                patch.set_alpha(0.65)
                
            ax.set_title("Tree Height Contrast by Species", fontsize=11, fontweight='bold', pad=12)
            ax.set_ylabel("Height (m)", fontsize=10)
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.grid(True, linestyle='--', alpha=0.5, color='#e0e0e0')
            
            fig.tight_layout()
            p = out_dir / "species_height_comparison.png"
            fig.savefig(p, dpi=150)
            plt.close(fig)
            produced.append(p)

    # 8. 各树种树冠投影面积差异箱线图
    if len(sp_names) > 1:
        sp_groups_a = []
        labels_a = []
        for sp in sp_names:
            grp = [o["crown_area"] for o in raw_obs if o.get("species") == sp and o.get("crown_area") is not None]
            if len(grp) >= 3:
                sp_groups_a.append(grp)
                labels_a.append(sp)
                
        if len(sp_groups_a) > 1:
            fig, ax = plt.subplots(figsize=(7, 4.8))
            box = ax.boxplot(
                sp_groups_a, patch_artist=True,
                showmeans=True, showfliers=True,
                boxprops=dict(facecolor="#e8f5e9", color="#2e7d32", linewidth=1.2),
                capprops=dict(color="#2e7d32", linewidth=1.2),
                whiskerprops=dict(color="#2e7d32", linestyle="--", linewidth=1.2),
                flierprops=dict(marker='o', markerfacecolor='#e57373', markersize=4, markeredgecolor='none'),
                medianprops=dict(color="#d84315", linewidth=1.5),
                meanprops=dict(marker='^', markerfacecolor='#1976d2', markeredgecolor='none', markersize=5)
            )
            ax.set_xticks(range(1, len(labels_a) + 1))
            ax.set_xticklabels(labels_a)
            
            for i, patch in enumerate(box['boxes']):
                patch.set_facecolor(COLORS[i % len(COLORS)])
                patch.set_alpha(0.65)
                
            ax.set_title("Crown Area Contrast by Species", fontsize=11, fontweight='bold', pad=12)
            ax.set_ylabel("Crown Area (m^2)", fontsize=10)
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.grid(True, linestyle='--', alpha=0.5, color='#e0e0e0')
            
            fig.tight_layout()
            p = out_dir / "species_area_comparison.png"
            fig.savefig(p, dpi=150)
            plt.close(fig)
            produced.append(p)

    log.info("生成报告图表 {} 张 -> {}", len(produced), out_dir)
    return produced


def to_pdf(data: ReportData, out_path: Path, *, charts: list[Path] | None = None, md_content: str = "") -> Path | None:
    """优先通过 markdown-pdf 转换工具生成 PDF，失败时使用 reportlab 优雅降级手工绘制。"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. 尝试使用 markdown-pdf 工具转制 PDF
    try:
        from markdown_pdf import MarkdownPdf, Section
        import re
        import base64
        
        # 将 Markdown 图片替换为 Base64 嵌入的 HTML img 标签，100% 解决绝对/相对路径渲染故障及跨目录安全加载限制
        def get_image_base64(p: Path) -> str:
            with open(p, "rb") as f:
                content = f.read()
            ext = p.suffix.lower().replace(".", "")
            mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
            b64_data = base64.b64encode(content).decode("utf-8")
            return f"data:{mime};base64,{b64_data}"

        absolute_md = md_content
        # 正则匹配 Markdown 中的图片：![caption](path)
        pattern = r"!\[([^\]]*)\]\(([^)]+)\)"
        
        def repl(match):
            caption = match.group(1)
            path_str = match.group(2)
            # 通过图片文件名从 charts 列表中匹配物理图片
            filename = Path(path_str).name
            target_chart = None
            for c in (charts or []):
                if c.name == filename:
                    target_chart = c
                    break
            
            if target_chart and target_chart.exists():
                try:
                    b64_uri = get_image_base64(target_chart)
                    # 替换为居中、最大宽度适配的 HTML img 标签
                    return f'<div style="text-align: center; margin: 15px 0;"><img src="{b64_uri}" alt="{caption}" style="max-width: 90%; height: auto; border-radius: 4px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);" /><p style="font-size: 9pt; color: #666; margin-top: 5px;">{caption}</p></div>'
                except Exception as ex:
                    log.warning("转换图片 {} 为 Base64 失败: {}", filename, ex)
            return match.group(0)

        absolute_md = re.sub(pattern, repl, absolute_md)
            
        pdf = MarkdownPdf(toc_level=2)
        pdf.add_section(Section(absolute_md))
        pdf.save(str(out_path))
        log.info("成功通过 markdown-pdf 工具转制 PDF -> {}", out_path)
        return out_path
    except Exception as e:
        log.warning("markdown-pdf 库不可用，转用 reportlab 渲染器手工绘制兜底: {}", e)

    # 2. 兜底渲染逻辑 (ReportLab)
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.pdfgen import canvas
    except Exception as rl_err:
        log.warning("reportlab 亦不可用，无法生成 PDF: {}", rl_err)
        return None

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
        except Exception as chart_err:
            log.warning("PDF 嵌入图表失败 {}: {}", chart, chart_err)

    c.showPage()
    c.save()
    log.info("生成 PDF (ReportLab 兜底) -> {}", out_path)
    return out_path
