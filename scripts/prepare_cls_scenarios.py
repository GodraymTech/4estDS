"""4estDS 树种分类数据集规整与分层划分脚本。

支持：
- 场景1: 纯正射双目录合并，剔除 GG，分层划分 7:2:1
- 场景2: 正射双目录 + 航拍单目录（3目录合并），剔除 GG，分层划分 7:2:1
- 相对软链接零拷贝落盘
- 自动生成数据分布统计与元数据清单
"""
from __future__ import annotations

import os
import random
import shutil
from pathlib import Path
from typing import Dict, List, Tuple
import json

ROOT_DIR = Path(__file__).resolve().parent.parent
BASE_DATA_DIR = ROOT_DIR / "data" / "for_clssify"
OUTPUT_SCENARIOS_DIR = BASE_DATA_DIR / "scenarios"

ORTHO_DIRS = [
    BASE_DATA_DIR / "train_forcls_6类含TREEGG_261010抠自4处正射",
    BASE_DATA_DIR / "train_forcls_8类含TREEGG_25抠自5处正射",
]
AERIAL_DIR = BASE_DATA_DIR / "train_forcls_8类含TREEGG_25抠自6处航拍"

EXCLUDE_CLASSES = {"GG"}
SEED = 42


def collect_samples_from_dirs(dirs: List[Path]) -> Dict[str, List[Path]]:
    """从给定的数据集目录列表中汇总各树种样本（排除 EXCLUDE_CLASSES）。"""
    class_to_samples: Dict[str, List[Path]] = {}
    for d in dirs:
        crops_dir = d / "crops"
        images_dir = d / "images"
        if not crops_dir.exists():
            continue
        for class_dir in crops_dir.iterdir():
            if not class_dir.is_dir():
                continue
            cls_name = class_dir.name
            if cls_name in EXCLUDE_CLASSES:
                continue
            if cls_name not in class_to_samples:
                class_to_samples[cls_name] = []
            
            # 读取所有图片文件，确保指向真实存在的图片文件
            for img_file in class_dir.glob("*"):
                real_file = (images_dir / img_file.name).resolve()
                if not real_file.exists():
                    real_file = img_file.resolve()
                if real_file.exists():
                    class_to_samples[cls_name].append(real_file)

    # 排序以确保可复现性
    for cls_name in class_to_samples:
        class_to_samples[cls_name] = sorted(list(set(class_to_samples[cls_name])))
    return class_to_samples


def stratified_split(
    class_to_samples: Dict[str, List[Path]],
    train_ratio: float = 0.7,
    val_ratio: float = 0.2,
    test_ratio: float = 0.1,
    seed: int = SEED,
) -> Dict[str, Dict[str, List[Path]]]:
    """对每个类别分别进行确定性的分层划分 (train, val, test)。"""
    rng = random.Random(seed)
    split_res: Dict[str, Dict[str, List[Path]]] = {
        "train": {},
        "val": {},
        "test": {},
    }

    for cls_name, samples in sorted(class_to_samples.items()):
        items = list(samples)
        rng.shuffle(items)
        n = len(items)

        if n == 0:
            for s in ("train", "val", "test"):
                split_res[s][cls_name] = []
            continue

        if n == 1:
            split_res["train"][cls_name] = items
            split_res["val"][cls_name] = []
            split_res["test"][cls_name] = []
            continue

        if n == 2:
            split_res["train"][cls_name] = items[:1]
            split_res["val"][cls_name] = items[1:]
            split_res["test"][cls_name] = []
            continue

        # n >= 3: 保证 train, val, test 均至少分配到 1 个样本
        n_test = max(1, int(round(n * test_ratio)))
        n_val = max(1, int(round(n * val_ratio)))
        n_train = n - n_val - n_test

        if n_train < 1:
            n_train = 1
            if n_val > n_test:
                n_val = max(1, n - n_train - n_test)
            else:
                n_test = max(1, n - n_train - n_val)

        train_items = items[:n_train]
        val_items = items[n_train : n_train + n_val]
        test_items = items[n_train + n_val :]

        split_res["train"][cls_name] = train_items
        split_res["val"][cls_name] = val_items
        split_res["test"][cls_name] = test_items

    return split_res


def materialize_dataset(
    target_dir: Path,
    split_res: Dict[str, Dict[str, List[Path]]],
) -> Dict[str, Dict[str, int]]:
    """在目标目录下以相对软链接创建 train/val/test 结构。"""
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    counts: Dict[str, Dict[str, int]] = {"train": {}, "val": {}, "test": {}, "total": {}}

    for split_name in ("train", "val", "test"):
        split_path = target_dir / split_name
        split_path.mkdir(parents=True, exist_ok=True)

        for cls_name, items in split_res[split_name].items():
            cls_path = split_path / cls_name
            cls_path.mkdir(parents=True, exist_ok=True)
            counts[split_name][cls_name] = len(items)
            counts["total"][cls_name] = counts["total"].get(cls_name, 0) + len(items)

            for item in items:
                link_path = cls_path / item.name
                rel_target = os.path.relpath(item, cls_path)
                link_path.symlink_to(rel_target)

    # 导出分发记录与统计 JSON
    summary_file = target_dir / "split_summary.json"
    summary_data = {
        "counts": counts,
        "splits": {
            s: {c: [p.name for p in plist] for c, plist in split_res[s].items()}
            for s in ("train", "val", "test")
        },
    }
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2, ensure_ascii=False)

    return counts


def main():
    print(f"=== 开始准备分类数据集场景 (根目录: {OUTPUT_SCENARIOS_DIR}) ===")
    OUTPUT_SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 场景1: 正射双目录
    print("\n[场景1] 正在处理纯正射双子目录合并...")
    s1_samples = collect_samples_from_dirs(ORTHO_DIRS)
    s1_split = stratified_split(s1_samples)
    s1_target = OUTPUT_SCENARIOS_DIR / "scenario1_ortho"
    s1_counts = materialize_dataset(s1_target, s1_split)

    print(f"场景1 数据集创建成功: {s1_target}")
    print(f"{'树种':<8} {'Train':<8} {'Val':<8} {'Test':<8} {'总计':<8}")
    for cls_name in sorted(s1_counts["total"].keys()):
        print(
            f"{cls_name:<8} {s1_counts['train'].get(cls_name, 0):<8} "
            f"{s1_counts['val'].get(cls_name, 0):<8} {s1_counts['test'].get(cls_name, 0):<8} "
            f"{s1_counts['total'][cls_name]:<8}"
        )
    total_s1 = sum(s1_counts["total"].values())
    print(f"场景1 总样本量: {total_s1} (Train: {sum(s1_counts['train'].values())}, Val: {sum(s1_counts['val'].values())}, Test: {sum(s1_counts['test'].values())})")

    # 2. 场景2: 3目录合并 (正射 + 航拍)
    print("\n[场景2] 正在处理3子目录合并 (正射 + 航拍)...")
    s2_samples = collect_samples_from_dirs(ORTHO_DIRS + [AERIAL_DIR])
    s2_split = stratified_split(s2_samples)
    s2_target = OUTPUT_SCENARIOS_DIR / "scenario2_ortho_aerial"
    s2_counts = materialize_dataset(s2_target, s2_split)

    print(f"场景2 数据集创建成功: {s2_target}")
    print(f"{'树种':<8} {'Train':<8} {'Val':<8} {'Test':<8} {'总计':<8}")
    for cls_name in sorted(s2_counts["total"].keys()):
        print(
            f"{cls_name:<8} {s2_counts['train'].get(cls_name, 0):<8} "
            f"{s2_counts['val'].get(cls_name, 0):<8} {s2_counts['test'].get(cls_name, 0):<8} "
            f"{s2_counts['total'][cls_name]:<8}"
        )
    total_s2 = sum(s2_counts["total"].values())
    print(f"场景2 总样本量: {total_s2} (Train: {sum(s2_counts['train'].values())}, Val: {sum(s2_counts['val'].values())}, Test: {sum(s2_counts['test'].values())})")
    print("\n=== 数据集准备完成！ ===")


if __name__ == "__main__":
    main()
