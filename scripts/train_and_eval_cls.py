"""4estDS 树种分类双场景训练、独立评测与基准对比脚本。

包含：
1. 场景1 (纯正射 7类) 训练与自域测试集全面评测
2. 场景2 (正射+航拍 7类) 训练与自域测试集全面评测
3. 交叉基准对比：场景2模型在场景1纯正射测试集上的跨域评估
4. 综合对比分析报告生成 (Acc, Top-5, Macro F1, Per-class F1, Confusion Matrix)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import torch
from loguru import logger
from PIL import Image
from ultralytics import YOLO


def calc_classification_metrics(y_true: List[str], y_pred: List[str], labels: List[str]) -> Tuple[Dict[str, Any], List[List[int]]]:
    """零外部依赖的纯原生分类评测指标计算 (Accuracy, Precision, Recall, F1, 混淆矩阵)。"""
    label_to_idx = {l: i for i, l in enumerate(labels)}
    num_classes = len(labels)
    conf_mat = [[0] * num_classes for _ in range(num_classes)]

    for yt, yp in zip(y_true, y_pred):
        if yt in label_to_idx and yp in label_to_idx:
            conf_mat[label_to_idx[yt]][label_to_idx[yp]] += 1

    report: Dict[str, Any] = {}
    macro_p, macro_r, macro_f1 = 0.0, 0.0, 0.0
    weighted_p, weighted_r, weighted_f1 = 0.0, 0.0, 0.0
    total_samples = len(y_true)

    for i, label in enumerate(labels):
        tp = conf_mat[i][i]
        fp = sum(conf_mat[r][i] for r in range(num_classes)) - tp
        fn = sum(conf_mat[i][c] for c in range(num_classes)) - tp
        support = sum(conf_mat[i])

        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0

        report[label] = {
            "precision": prec,
            "recall": rec,
            "f1-score": f1,
            "support": support,
        }
        macro_p += prec
        macro_r += rec
        macro_f1 += f1

        weighted_p += prec * support
        weighted_r += rec * support
        weighted_f1 += f1 * support

    n_cls = max(1, num_classes)
    report["macro avg"] = {
        "precision": macro_p / n_cls,
        "recall": macro_r / n_cls,
        "f1-score": macro_f1 / n_cls,
        "support": total_samples,
    }
    report["weighted avg"] = {
        "precision": weighted_p / total_samples if total_samples > 0 else 0.0,
        "recall": weighted_r / total_samples if total_samples > 0 else 0.0,
        "f1-score": weighted_f1 / total_samples if total_samples > 0 else 0.0,
        "support": total_samples,
    }
    return report, conf_mat

ROOT_DIR = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = ROOT_DIR / "data" / "for_clssify" / "scenarios"
OUTPUTS_DIR = ROOT_DIR / ".4estDS" / "outputs"
OFFICIAL_WEIGHTS = Path("/home/ray/rays/repos/mds_patent/models/weights/yolo26s-cls-Official.pt")

SPECIES_NAMES = ["BGR", "HHL", "ML", "QQ", "THS", "TREE", "WBHS"]
SPECIES_MAP_CN = {
    "QQ": "秋茄",
    "HHL": "红海榄",
    "THS": "桐花树",
    "ML": "木榄",
    "BGR": "白骨壤",
    "WBHS": "无瓣海桑",
    "TREE": "红树",
}


def evaluate_model_on_dataset(
    model_path: Path,
    dataset_test_dir: Path,
    device: str = "cuda:0",
    batch_size: int = 128,
    imgsz: int = 224,
) -> Dict[str, Any]:
    """对给定模型在特定测试集目录（包含各类别子目录）上做纯推理评测与指标分析。"""
    logger.info(f"正在评测模型: {model_path} 测试集: {dataset_test_dir}")
    model = YOLO(str(model_path))

    # 1. 扫描测试集所有样本
    class_dirs = sorted([d for d in dataset_test_dir.iterdir() if d.is_dir()])
    y_true: List[str] = []
    y_pred: List[str] = []
    y_true_indices: List[int] = []
    y_pred_probs: List[np.ndarray] = []
    image_paths: List[Path] = []

    # 类别映射与索引
    model_names = model.names
    name_to_idx = {name: idx for idx, name in model_names.items()}

    for c_dir in class_dirs:
        gt_cls = c_dir.name
        for img_p in sorted(c_dir.glob("*.jpg")):
            image_paths.append(img_p)
            y_true.append(gt_cls)
            y_true_indices.append(name_to_idx.get(gt_cls, -1))

    # 2. 批量预测
    start_t = time.time()
    top1_correct = 0
    top5_correct = 0
    total = len(image_paths)

    for i in range(0, total, batch_size):
        batch_paths = [str(p) for p in image_paths[i : i + batch_size]]
        results = model.predict(
            batch_paths,
            imgsz=imgsz,
            device=device,
            batch=batch_size,
            verbose=False,
        )
        for j, res in enumerate(results):
            probs = res.probs
            top1_idx = int(probs.top1)
            pred_cls = model_names[top1_idx]
            y_pred.append(pred_cls)
            y_pred_probs.append(probs.data.cpu().numpy())

            gt_c = y_true[i + j]
            if pred_cls == gt_c:
                top1_correct += 1

            # Top-5
            top5_indices = probs.top5
            gt_idx = name_to_idx.get(gt_c, -1)
            if gt_idx in top5_indices:
                top5_correct += 1

    infer_time = time.time() - start_t
    top1_acc = top1_correct / total if total > 0 else 0.0
    top5_acc = top5_correct / total if total > 0 else 0.0

    # 3. 计算精确率、召回率、F1、混淆矩阵
    labels_present = sorted(list(set(y_true) | set(y_pred)))
    clf_report, conf_mat = calc_classification_metrics(y_true, y_pred, labels_present)

    metrics = {
        "total_samples": total,
        "inference_time_sec": round(infer_time, 2),
        "throughput_fps": round(total / infer_time, 1) if infer_time > 0 else 0,
        "top1_acc": round(top1_acc * 100, 2),
        "top5_acc": round(top5_acc * 100, 2),
        "macro_precision": round(clf_report["macro avg"]["precision"] * 100, 2),
        "macro_recall": round(clf_report["macro avg"]["recall"] * 100, 2),
        "macro_f1": round(clf_report["macro avg"]["f1-score"] * 100, 2),
        "weighted_f1": round(clf_report["weighted avg"]["f1-score"] * 100, 2),
        "classification_report": clf_report,
        "confusion_matrix": conf_mat,
        "labels": labels_present,
    }
    return metrics


def train_scenario(
    scenario_name: str,
    data_dir: Path,
    epochs: int = 80,
    batch_size: int = 128,
    patience: int = 15,
    imgsz: int = 224,
    device: str = "0",
    seed: int = 42,
    skip_existing: bool = True,
) -> Path:
    """运行 Ultralytics 分类模型训练。"""
    run_name = f"train_cls_{scenario_name}"
    best_weights = OUTPUTS_DIR / run_name / "weights" / "best.pt"
    if skip_existing and best_weights.exists():
        logger.info(f"检测到场景 {scenario_name} 的最佳模型权重已存在: {best_weights}，直接复用该权重。")
        return best_weights

    logger.info(f"=== 开始训练场景: {scenario_name} ===")
    logger.info(f"数据集目录: {data_dir}")
    logger.info(f"基底模型: {OFFICIAL_WEIGHTS}")
    
    model = YOLO(str(OFFICIAL_WEIGHTS))
    
    train_args = {
        "data": str(data_dir.resolve()),
        "epochs": epochs,
        "patience": patience,
        "batch": batch_size,
        "imgsz": imgsz,
        "optimizer": "auto",
        "seed": seed,
        "device": device,
        "workers": 8,
        "project": str(OUTPUTS_DIR.resolve()),
        "name": run_name,
        "exist_ok": True,
        "verbose": True,
    }
    
    results = model.train(**train_args)
    best_weights = OUTPUTS_DIR / run_name / "weights" / "best.pt"
    if not best_weights.exists():
        best_weights = OUTPUTS_DIR / run_name / "weights" / "last.pt"
    logger.info(f"场景 {scenario_name} 训练完成！最佳模型权重: {best_weights}")
    return best_weights


def generate_comparison_report(
    s1_self_metrics: Dict[str, Any],
    s2_self_metrics: Dict[str, Any],
    s2_on_s1_metrics: Dict[str, Any],
    output_path: Path,
) -> str:
    """生成专业的双场景对比分析 Markdown 报告。"""
    report_lines = []
    report_lines.append("# 树种细粒度分类训练与跨场景对比评测报告")
    report_lines.append("")
    report_lines.append(f"> 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("> 基底架构: YOLO26s-cls (Official Pretrained)")
    report_lines.append("> 硬件环境: NVIDIA GeForce RTX 4090 (24GB)")
    report_lines.append("")
    report_lines.append("## 一、场景全局综合指标对比")
    report_lines.append("")
    report_lines.append("| 评测维度 | 场景1：纯正射 (自域测试) | 场景2：正射+航拍 (自域测试) | 场景2模型在正射基准 (跨域评估) | 航拍数据对正射的增益 |")
    report_lines.append("| :--- | :---: | :---: | :---: | :---: |")
    
    s1_acc = s1_self_metrics["top1_acc"]
    s2_acc = s2_self_metrics["top1_acc"]
    s2_cross_acc = s2_on_s1_metrics["top1_acc"]
    delta_acc = s2_cross_acc - s1_acc
    delta_acc_str = f"{'+' if delta_acc >= 0 else ''}{delta_acc:.2f}%"

    s1_mf1 = s1_self_metrics["macro_f1"]
    s2_mf1 = s2_self_metrics["macro_f1"]
    s2_cross_mf1 = s2_on_s1_metrics["macro_f1"]
    delta_mf1 = s2_cross_mf1 - s1_mf1
    delta_mf1_str = f"{'+' if delta_mf1 >= 0 else ''}{delta_mf1:.2f}%"

    s1_wf1 = s1_self_metrics["weighted_f1"]
    s2_wf1 = s2_self_metrics["weighted_f1"]
    s2_cross_wf1 = s2_on_s1_metrics["weighted_f1"]
    delta_wf1 = s2_cross_wf1 - s1_wf1
    delta_wf1_str = f"{'+' if delta_wf1 >= 0 else ''}{delta_wf1:.2f}%"

    report_lines.append(f"| **Top-1 准确率 (Acc)** | **{s1_acc}%** | **{s2_acc}%** | **{s2_cross_acc}%** | **{delta_acc_str}** |")
    report_lines.append(f"| **Top-5 准确率** | {s1_self_metrics['top5_acc']}% | {s2_self_metrics['top5_acc']}% | {s2_on_s1_metrics['top5_acc']}% | {('+' if s2_on_s1_metrics['top5_acc'] - s1_self_metrics['top5_acc'] >= 0 else '')}{s2_on_s1_metrics['top5_acc'] - s1_self_metrics['top5_acc']:.2f}% |")
    report_lines.append(f"| **宏平均 F1 (Macro F1)** | **{s1_mf1}%** | **{s2_mf1}%** | **{s2_cross_mf1}%** | **{delta_mf1_str}** |")
    report_lines.append(f"| **加权平均 F1 (Weighted F1)** | **{s1_wf1}%** | **{s2_wf1}%** | **{s2_cross_wf1}%** | **{delta_wf1_str}** |")
    report_lines.append(f"| **测试集样本量** | {s1_self_metrics['total_samples']} | {s2_self_metrics['total_samples']} | {s2_on_s1_metrics['total_samples']} (正射基准) | -- |")
    report_lines.append(f"| **推理吞吐速度** | {s1_self_metrics['throughput_fps']} FPS | {s2_self_metrics['throughput_fps']} FPS | {s2_on_s1_metrics['throughput_fps']} FPS | -- |")
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")
    report_lines.append("## 二、按树种细粒度 F1-Score 对比 (正射黄金基准)")
    report_lines.append("")
    report_lines.append("| 树种代码 | 树种中文名称 | 场景1模型正射 F1 | 场景2模型正射 F1 | 增益 / 差异 | 正射基准样本数 |")
    report_lines.append("| :--- | :--- | :---: | :---: | :---: | :---: |")

    labels = sorted(list(s1_self_metrics["classification_report"].keys()))
    for label in labels:
        if label in ("accuracy", "macro avg", "weighted avg"):
            continue
        cn_name = SPECIES_MAP_CN.get(label, label)
        f1_s1 = round(s1_self_metrics["classification_report"][label]["f1-score"] * 100, 2)
        
        s2_rep = s2_on_s1_metrics["classification_report"].get(label, {"f1-score": 0.0, "support": 0})
        f1_s2 = round(s2_rep["f1-score"] * 100, 2)
        supp = s1_self_metrics["classification_report"][label]["support"]
        
        d_f1 = f1_s2 - f1_s1
        d_f1_str = f"{'+' if d_f1 >= 0 else ''}{d_f1:.2f}%"
        report_lines.append(f"| **{label}** | {cn_name} | {f1_s1}% | {f1_s2}% | {d_f1_str} | {supp} |")

    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")
    report_lines.append("## 三、核心发现与林业遥感专业分析")
    report_lines.append("")
    if delta_acc >= 0:
        report_lines.append(f"1. **多视角航拍特征正向迁移**：场景2引入低空航拍切片后，在纯正射基准上的 Top-1 准确率变动了 **{delta_acc_str}**，表明多视角的树冠纹理增强了模型的表征鲁棒性。")
    else:
        report_lines.append(f"1. **视角域迁移影响**：场景2模型在纯正射基准上的准确率变动了 **{delta_acc_str}**。航拍倾斜拍摄带来的侧面枝叶纹理与正射垂直俯视存在一定视角域差异。")

    report_lines.append(f"2. **长尾树种表现**：对于木榄 (ML) 与无瓣海桑 (WBHS) 等稀缺长尾样本，分层 7:2:1 抽样保证了评估闭环。")
    report_lines.append("")

    report_text = "\n".join(report_lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    return report_text


def main():
    parser = argparse.ArgumentParser(description="4estDS 树种分类训练与评估")
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--patience", type=int, default=15)
    parser.add_argument("--imgsz", type=int, default=224)
    parser.add_argument("--device", type=str, default="0")
    args = parser.parse_args()

    s1_dir = SCENARIOS_DIR / "scenario1_ortho"
    s2_dir = SCENARIOS_DIR / "scenario2_ortho_aerial"

    # 1. 训练场景1
    s1_weights = train_scenario(
        "scenario1_ortho",
        s1_dir,
        epochs=args.epochs,
        batch_size=args.batch_size,
        patience=args.patience,
        imgsz=args.imgsz,
        device=args.device,
    )

    # 2. 评测场景1 (自域)
    s1_self_metrics = evaluate_model_on_dataset(
        s1_weights,
        s1_dir / "test",
        device=f"cuda:{args.device}",
        batch_size=args.batch_size,
        imgsz=args.imgsz,
    )

    # 3. 训练场景2
    s2_weights = train_scenario(
        "scenario2_ortho_aerial",
        s2_dir,
        epochs=args.epochs,
        batch_size=args.batch_size,
        patience=args.patience,
        imgsz=args.imgsz,
        device=args.device,
    )

    # 4. 评测场景2 (自域)
    s2_self_metrics = evaluate_model_on_dataset(
        s2_weights,
        s2_dir / "test",
        device=f"cuda:{args.device}",
        batch_size=args.batch_size,
        imgsz=args.imgsz,
    )

    # 5. 跨域交叉评测：场景2模型在场景1测试集 (正射基准)
    s2_on_s1_metrics = evaluate_model_on_dataset(
        s2_weights,
        s1_dir / "test",
        device=f"cuda:{args.device}",
        batch_size=args.batch_size,
        imgsz=args.imgsz,
    )

    # 6. 生成对比报告
    report_path = OUTPUTS_DIR / "classification_scenarios_comparison_report.md"
    generate_comparison_report(
        s1_self_metrics,
        s2_self_metrics,
        s2_on_s1_metrics,
        report_path,
    )
    logger.info(f"🎉 评测与对比完成！综合报告已保存至: {report_path}")


if __name__ == "__main__":
    main()
