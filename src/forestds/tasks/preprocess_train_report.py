"""模型训练数据集预处理报告生成与可视化模块。

负责四张数据画像大表的指标统计、Markdown 排版格式化，以及 Matplotlib 尺寸直方图绘制。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple, Set
import numpy as np

# 强制设置 Matplotlib 在无 GUI 终端运行，并解决字体乱码与 Unicode 缺失 Glyph 警报
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import fontManager

# 注入健壮字体列表
font_candidates = [
    'DejaVu Sans',
    'WenQuanYi Micro Hei', 
    'Noto Sans CJK SC', 
    'SimHei', 
    'SimSun', 
    'Microsoft YaHei'
]
found_fonts = [f.name for f in fontManager.ttflist if f.name in font_candidates]
plt.rcParams['font.sans-serif'] = found_fonts + font_candidates + ['DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

logger = logging.getLogger("forestds")


def _get_metric_stats(ws: np.ndarray) -> Dict[str, float]:
    if len(ws) == 0:
        return {"mean": 0.0, "std": 0.0, "min": 0.0, "med": 0.0, "max": 0.0}
    return {
        "mean": float(np.mean(ws)),
        "std": float(np.std(ws)),
        "min": float(np.min(ws)),
        "med": float(np.median(ws)),
        "max": float(np.max(ws))
    }


def generate_plots_and_report(
    dest_path: Path,
    raw_box_records: List[Dict[str, Any]],
    pre_scan_samples: Dict[str, Dict[str, Any]], # {"new": {"pos": [...], "neg": [...]}, "old": ...}
    post_split_stats: Dict[str, Dict[str, Any]], # {"train": {"pos": [...], "neg": [...]}, "val": ...}
    global_classes: List[str]
) -> None:
    """计算预处理前后的数据特征画像大表，绘制尺寸分布直方图，输出 Markdown 报告。"""
    
    # 1. 绘制尺寸分布直方图 (使用英文标签，100% 杜绝 Glyph 缺失警告)
    widths_640 = [b["w_norm_640"] for b in raw_box_records]
    
    if widths_640:
        try:
            fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
            
            ax.hist(widths_640, bins=30, color="#1976d2", edgecolor="white", alpha=0.8)
            ax.set_title("Normalized BBox Width Distribution (640px Scale)", fontsize=12, fontweight="bold")
            ax.set_xlabel("Normalized Width (pixels)", fontsize=10)
            ax.set_ylabel("Frequency", fontsize=10)
            ax.grid(True, linestyle="--", alpha=0.5)
            
            fig.tight_layout()
            chart_path = dest_path / "distribution_report.png"
            fig.savefig(chart_path, bbox_inches="tight")
            plt.close(fig)
            logger.debug(f"成功绘制数据分布直方图: {chart_path}")
        except Exception as plot_err:
            logger.warning(f"绘制 Matplotlib 图表失败 (已自动跳过图表，保留数据统计): {plot_err}")
            
    # 2. 计算 大表 A (预处理前：叶子节点单木归一化标注框尺寸特征表)
    table_a_rows = []
    groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    for b in raw_box_records:
        key = (b["origin"], b["leaf_node"], b["species"])
        groups.setdefault(key, []).append(b)
        
    nodes_found = sorted(list(set((b["origin"], b["leaf_node"]) for b in raw_box_records)))
    for orig, leaf in nodes_found:
        orig_name = "增量集 (New)" if orig == "new" else "主集 (Old)"
        
        node_species = sorted(list(set(b["species"] for b in raw_box_records if b["origin"] == orig and b["leaf_node"] == leaf)))
        node_boxes = [b for b in raw_box_records if b["origin"] == orig and b["leaf_node"] == leaf]
        
        for sp in node_species:
            sp_boxes = groups.get((orig, leaf, sp), [])
            stats = _get_metric_stats(np.array([b["w_norm_640"] for b in sp_boxes]))
            table_a_rows.append({
                "orig": orig_name,
                "leaf": leaf,
                "sp": sp,
                "cnt": len(sp_boxes),
                "mean": stats["mean"], "std": stats["std"], "min": stats["min"], "med": stats["med"], "max": stats["max"]
            })
            
        node_stats = _get_metric_stats(np.array([b["w_norm_640"] for b in node_boxes]))
        table_a_rows.append({
            "orig": orig_name,
            "leaf": leaf,
            "sp": "**Total (合计)**",
            "cnt": len(node_boxes),
            "mean": node_stats["mean"], "std": node_stats["std"], "min": node_stats["min"], "med": node_stats["med"], "max": node_stats["max"]
        })

    # 3. 计算 大表 B (预处理前与采纳样本分布及采纳转化大表)
    table_b_rows = []
    
    # 提取新/旧数据集的原始扫描列表
    new_pos_list = pre_scan_samples.get("new", {}).get("pos", [])
    old_pos_list = pre_scan_samples.get("old", {}).get("pos", [])
    new_neg_list = pre_scan_samples.get("new", {}).get("neg", []) # List[Tuple[Path, str]]
    old_neg_list = pre_scan_samples.get("old", {}).get("neg", [])
    
    # 提取最终划分在 train/val 里的样本
    train_pos = post_split_stats.get("train", {}).get("pos", [])
    val_pos = post_split_stats.get("val", {}).get("pos", [])
    final_pos_all = train_pos + val_pos
    
    train_neg = post_split_stats.get("train", {}).get("neg", []) # List[Dict]
    val_neg = post_split_stats.get("val", {}).get("neg", [])
    final_neg_all = train_neg + val_neg

    # 寻找所有的实体 (origin, name, is_background)
    entities: Dict[Tuple[str, str, bool], Dict[str, Any]] = {}
    
    # a. 填充扫描到的正样本
    for s in new_pos_list:
        k = ("new", s.get("node_name", "."), False)
        entities.setdefault(k, {"scan_pos": 0, "final_pos": 0, "scan_neg": 0, "final_neg_unique": set(), "final_neg_total": 0, "boxes": 0})
        entities[k]["scan_pos"] += 1
        
    for s in old_pos_list:
        k = ("old", s.get("node_name", "."), False)
        entities.setdefault(k, {"scan_pos": 0, "final_pos": 0, "scan_neg": 0, "final_neg_unique": set(), "final_neg_total": 0, "boxes": 0})
        entities[k]["scan_pos"] += 1
        
    # b. 填充扫描到的负样本
    for img_p, belong_name in new_neg_list:
        is_bg = belong_name.startswith("background_")
        k = ("new", belong_name, is_bg)
        entities.setdefault(k, {"scan_pos": 0, "final_pos": 0, "scan_neg": 0, "final_neg_unique": set(), "final_neg_total": 0, "boxes": 0})
        entities[k]["scan_neg"] += 1
        
    for img_p, belong_name in old_neg_list:
        is_bg = belong_name.startswith("background_")
        k = ("old", belong_name, is_bg)
        entities.setdefault(k, {"scan_pos": 0, "final_pos": 0, "scan_neg": 0, "final_neg_unique": set(), "final_neg_total": 0, "boxes": 0})
        entities[k]["scan_neg"] += 1

    # c. 填充最终采纳的正样本
    for s in final_pos_all:
        origin = "new" if s in new_pos_list else "old"
        k = (origin, s.get("node_name", "."), False)
        if k in entities:
            entities[k]["final_pos"] += 1
            entities[k]["boxes"] += len(s["bboxes"])
            
    # d. 填充最终采纳的负样本
    for item in final_neg_all:
        orig = item["origin"]
        belong = item["belong_name"]
        img_p = item["img_path"]
        is_bg = belong.startswith("background_")
        
        k = (orig, belong, is_bg)
        if k in entities:
            entities[k]["final_neg_unique"].add(img_p)
            entities[k]["final_neg_total"] += 1

    # 用来累计合计行的全局变量
    tot_scan_pos = 0
    tot_final_pos = 0
    tot_scan_neg = 0
    tot_final_neg_unique = set()
    tot_final_neg_total = 0
    tot_boxes = 0

    for (orig, name, is_bg), data in sorted(entities.items(), key=lambda x: (x[0][0], x[0][2], x[0][1])):
        orig_name = "增量集 (New)" if orig == "new" else "主集 (Old)"
        
        scan_p = data["scan_pos"]
        final_p = data["final_pos"]
        scan_n = data["scan_neg"]
        final_n_uniq = len(data["final_neg_unique"])
        final_n_tot = data["final_neg_total"]
        
        tot_scan_pos += scan_p
        tot_final_pos += final_p
        tot_scan_neg += scan_n
        tot_final_neg_unique.update(data["final_neg_unique"])
        tot_final_neg_total += final_n_tot
        tot_boxes += data["boxes"]
        
        # 正样本采纳百分比后缀
        pos_pct = (final_p / scan_p * 100) if scan_p > 0 else 0.0
        pos_final_str = f"{final_p} *({pos_pct:.1f}%)*"
        
        # 负样本采纳百分比后缀（去重采纳率）
        neg_pct = (final_n_uniq / scan_n * 100) if scan_n > 0 else 0.0
        if final_n_tot > final_n_uniq:
            neg_final_str = f"{final_n_tot} *({neg_pct:.1f}%, 含 {final_n_tot - final_n_uniq}张过采样)*"
        else:
            neg_final_str = f"{final_n_tot} *({neg_pct:.1f}%)*"
            
        scan_total_imgs = scan_p + scan_n
        final_total_imgs = final_p + final_n_tot
        avg_boxes = (data["boxes"] / final_p) if final_p > 0 else 0.0
        
        table_b_rows.append({
            "orig": orig_name,
            "name": f"`{name}`" + (" (背景负样本)" if is_bg else ""),
            "scan_pos": scan_p,
            "final_pos": pos_final_str,
            "scan_neg": scan_n,
            "final_neg": neg_final_str,
            "scan_tot": scan_total_imgs,
            "final_tot": final_total_imgs,
            "boxes": data["boxes"],
            "avg_boxes": f"{avg_boxes:.2f}"
        })
        
    # 计算合计行百分比
    tot_pos_pct = (tot_final_pos / tot_scan_pos * 100) if tot_scan_pos > 0 else 0.0
    tot_pos_final_str = f"**{tot_final_pos}** *({tot_pos_pct:.1f}%)*"
    
    tot_neg_uniq_cnt = len(tot_final_neg_unique)
    tot_neg_pct = (tot_neg_uniq_cnt / tot_scan_neg * 100) if tot_scan_neg > 0 else 0.0
    
    if tot_final_neg_total > tot_neg_uniq_cnt:
        tot_neg_final_str = f"**{tot_final_neg_total}** *({tot_neg_pct:.1f}%, 含 {tot_final_neg_total - tot_neg_uniq_cnt}张过采样)*"
    else:
        tot_neg_final_str = f"**{tot_final_neg_total}** *({tot_neg_pct:.1f}%)*"
        
    total_avg_boxes = (tot_boxes / tot_final_pos) if tot_final_pos > 0 else 0.0
        
    table_b_rows.append({
        "orig": "**Total (合计)**",
        "name": "-",
        "scan_pos": f"**{tot_scan_pos}**",
        "final_pos": tot_pos_final_str,
        "scan_neg": f"**{tot_scan_neg}**",
        "final_neg": tot_neg_final_str,
        "scan_tot": f"**{tot_scan_pos + tot_scan_neg}**",
        "final_tot": f"**{tot_final_pos + tot_final_neg_total}**",
        "boxes": f"**{tot_boxes}**",
        "avg_boxes": f"**{total_avg_boxes:.2f}**"
    })

    # 4. 计算 大表 C (预处理后：最终划分子集分布表)
    table_c_rows = []
    splits = ["train", "val"]
    total_pos_c = 0
    total_neg_c = 0
    total_boxes_c = 0
    max_boxes_in_single = 0
    
    for split in splits:
        pos_imgs = post_split_stats.get(split, {}).get("pos", [])
        neg_imgs = post_split_stats.get(split, {}).get("neg", []) # List[Dict]
        
        cnt_pos = len(pos_imgs)
        cnt_neg = len(neg_imgs)
        cnt_tot = cnt_pos + cnt_neg
        
        boxes_cnt = sum(len(s["bboxes"]) for s in pos_imgs)
        max_box = max([len(s["bboxes"]) for s in pos_imgs] + [0])
        
        total_pos_c += cnt_pos
        total_neg_c += cnt_neg
        total_boxes_c += boxes_cnt
        max_boxes_in_single = max(max_boxes_in_single, max_box)
        
        table_c_rows.append({
            "split": f"**{split.capitalize()} (子集)**",
            "tot": cnt_tot,
            "pos": cnt_pos,
            "neg": cnt_neg,
            "neg_ratio": f"{(cnt_neg / cnt_tot):.1%}" if cnt_tot > 0 else "0.0%",
            "boxes": boxes_cnt,
            "avg_boxes": f"{(boxes_cnt / cnt_pos):.2f}" if cnt_pos > 0 else "0.00",
            "max_box": max_box
        })
        
    table_c_rows.append({
        "split": "**Total (合计)**",
        "tot": total_pos_c + total_neg_c,
        "pos": total_pos_c,
        "neg": total_neg_c,
        "neg_ratio": f"{(total_neg_c / (total_pos_c + total_neg_c)):.1%}" if (total_pos_c + total_neg_c) > 0 else "0.0%",
        "boxes": total_boxes_c,
        "avg_boxes": f"{(total_boxes_c / total_pos_c):.2f}" if total_pos_c > 0 else "0.00",
        "max_box": max_boxes_in_single
    })

    # 5. 计算 大表 D (预处理后：合并混洗类别特征表)
    table_d_rows = []
    class_split_stats: Dict[str, Dict[str, int]] = {cls_name: {"train": 0, "val": 0} for cls_name in global_classes}
    for split in splits:
        for s in post_split_stats.get(split, {}).get("pos", []):
            for bbox in s["bboxes"]:
                cls_name = bbox[0]
                if cls_name in class_split_stats:
                    class_split_stats[cls_name][split] += 1
                    
    for cls_name in global_classes:
        tr_cnt = class_split_stats[cls_name]["train"]
        va_cnt = class_split_stats[cls_name]["val"]
        tot_cnt = tr_cnt + va_cnt
        table_d_rows.append({
            "class": cls_name,
            "train_cnt": tr_cnt,
            "train_ratio": f"{(tr_cnt / total_boxes_c):.2%}" if total_boxes_c > 0 else "0.0%",
            "val_cnt": va_cnt,
            "val_ratio": f"{(va_cnt / total_boxes_c):.2%}" if total_boxes_c > 0 else "0.0%",
            "tot_cnt": tot_cnt,
            "tot_ratio": f"{(tot_cnt / total_boxes_c):.2%}" if total_boxes_c > 0 else "0.0%",
        })

    # 6. 生成并写入 distribution_report.md
    report_path = dest_path / "distribution_report.md"
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("# 4estDS 训练集数据画像与分布报告\n\n")
            f.write("> [!NOTE]\n")
            f.write("> 本报告由训练预处理系统自动生成，包含预处理前各叶子节点/背景目录画像，以及规整划分子集后的特征表征。\n\n")
            
            # --- 第一部分：预处理前数据画像 ---
            f.write("## 1. 预处理前：原始数据分布画像 (Pre-processing Dataset Profiling)\n\n")
            
            f.write("### 📊 大表 A：树木边界框尺寸与数量特征表 (BBox Size Characterization by Leaf Nodes)\n")
            f.write("> [!TIP]\n")
            f.write("> 下表中的宽度指标已等比例归一化至统一的 640px 标准画幅（$W_{640} = \\frac{W_{abs}}{W_{image}} \\times 640.0$），可直接跨数据集进行尺度对比。\n\n")
            f.write("| 数据集来源 | 叶子节点目录 | 树种 (Species) | 标注框数 (Count) | 归一化宽度 Mean±Std (px) | 归一化宽度 Min~Max (px) | 归一化宽度 Median (px) |\n")
            f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
            for row in table_a_rows:
                w_ms = f"{row['mean']:.1f}±{row['std']:.1f}"
                w_mm = f"{row['min']:.1f}~{row['max']:.1f}"
                f.write(f"| {row['orig']} | `{row['leaf']}` | {row['sp']} | {row['cnt']} | {w_ms} | {w_mm} | {row['med']:.1f} |\n")
            f.write("\n")
            
            f.write("### 🖼️ 大表 B：各叶子节点与背景目录样本分布与采纳转化表 (Sample Distribution & Acceptance by Leaf Nodes & Backgrounds)\n")
            f.write("| 数据集来源 | 叶子节点 / 背景目录 | 扫描正样本数 | 最终采纳正样本数 | 扫描负样本数 | 最终采纳负样本数 | 探测总图数 | 最终采纳总图数 | 总标注框数 | 平均正样本框数 |\n")
            f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
            for row in table_b_rows:
                f.write(f"| {row['orig']} | {row['name']} | {row['scan_pos']} | {row['final_pos']} | {row['scan_neg']} | {row['final_neg']} | {row['scan_tot']} | {row['final_tot']} | {row['boxes']} | {row['avg_boxes']} |\n")
            f.write("\n\n")
            
            # --- 第二部分：预处理后数据画像 ---
            f.write("## 2. 预处理后：合并混洗划分子集特征 (Post-processing Profiling)\n\n")
            
            f.write("### 📈 大表 C：合并混洗后训练集/验证集分布特征表 (Subset Distributions after Shuffle & Splits)\n")
            f.write("| 划分子集 | 图像总数 | 正样本图片数 | 负样本图片数 | 负样本占比 (%) | 总目标框数 | 平均每正样本框数 | 单图最多框数 |\n")
            f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
            for row in table_c_rows:
                f.write(f"| {row['split']} | {row['tot']} | {row['pos']} | {row['neg']} | {row['neg_ratio']} | {row['boxes']} | {row['avg_boxes']} | {row['max_box']} |\n")
            f.write("\n")
            
            f.write("### 🌲 大表 D：全局类别各子集分布特征表 (Class Multi-subset Characterization)\n")
            f.write("| 类别名称 (Class Name) | Train 标注框数 | Train 占比 (%) | Val 标注框数 | Val 占比 (%) | 总标注框数 | 总占比 (%) |\n")
            f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
            for row in table_d_rows:
                f.write(f"| **{row['class']}** | {row['train_cnt']} | {row['train_ratio']} | {row['val_cnt']} | {row['val_ratio']} | {row['tot_cnt']} | {row['tot_ratio']} |\n")
            f.write("\n\n")
            
            # --- 第三部分：直方图尺度曲线 ---
            f.write("## 3. 目标框尺度特征分布 (BBox Scale Characteristics)\n\n")
            if widths_640:
                f.write(f"- **平均归一化标注框宽度**: {np.mean(widths_640):.1f} 像素\n")
                f.write(f"- **等效 640px 归一化中位数**: {np.median(widths_640):.1f} 像素\n\n")
                f.write("### 尺度直方分布图 (BBox Scale Histograms)\n\n")
                f.write("![BBox Scale Histograms](distribution_report.png)\n")
            else:
                f.write("未检测到有效标注框，无法进行直方图尺度特征提取。\n")
                
        logger.info(f"数据画像报告 markdown 成功写入至: {report_path}")
    except Exception as md_err:
        logger.error(f"写入数据画像报告失败: {md_err}")
