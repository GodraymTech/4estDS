"""针对模型训练的数据集自适应预处理与规整模块。

支持 YOLO, VOC, COCO 格式以及任意嵌套子目录的自适应配对、负样本采样、新旧数据集混合、过采样占比红线控制、8:2划分、以及分布直方图与 Markdown 报告的自动生成。
"""
from __future__ import annotations

import os
import json
import random
import shutil
import math
import xml.etree.ElementTree as ET
import yaml
from pathlib import Path
from typing import Any, Dict, List, Tuple, Set
from PIL import Image
from loguru import logger

# 引入项目配置与算子
from forestds import paths
from forestds.utils.annotations import parse_voc_file, SUPPORTED_IMAGE_EXTS, find_image_for_xml


def safe_link(src: Path, dst: Path) -> None:
    """安全地创建软链接，若失败则降级为文件拷贝。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        os.symlink(src, dst)
    except Exception as e:
        logger.debug(f"软链接失败，降级为文件拷贝: {src} -> {dst}. 原因: {e}")
        try:
            shutil.copy2(src, dst)
        except Exception:
            pass


def process_and_link_image(src: Path, dst: Path) -> None:
    """自适应处理图像通道并进行软链接挂载。
    
    如果是标准 3通道 RGB，直接创建软链接；
    如果是多通道、RGBA、灰度等，转为 RGB 并存入目标，以防止 YOLO Mosaic 数据增强报错。
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
        
    try:
        with Image.open(src) as img:
            if img.mode == "RGB":
                os.symlink(src, dst)
            else:
                logger.debug(f"图像 {src.name} 模式为 {img.mode}，自动转换为 RGB 格式保存...")
                rgb_img = img.convert("RGB")
                rgb_img.save(dst)
    except Exception as e:
        logger.warning(f"自适应处理图像 {src.name} 通道失败: {e}，降级为直接拷贝。")
        try:
            shutil.copy2(src, dst)
        except Exception:
            pass


def load_coco_annotations(json_path: Path) -> Dict[str, Tuple[List[Dict[str, Any]], Dict[int, str]]]:
    """尝试加载 COCO 格式的标注 JSON 文件。
    
    返回:
        映射: {img_stem.lower(): (bbox_list_of_dict, id_to_class)}
    """
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            coco_data = json.load(f)
            
        if not isinstance(coco_data, dict) or "images" not in coco_data or "annotations" not in coco_data:
            return {}
            
        # 解析 categories
        id_to_class = {}
        if "categories" in coco_data:
            for cat in coco_data["categories"]:
                id_to_class[cat["id"]] = cat["name"]
                
        # 建立 image_id 到图片文件名的映射
        img_id_to_info = {}
        for img in coco_data["images"]:
            img_id_to_info[img["id"]] = img
            
        # 整理 annotations
        img_stem_to_annos = {}
        for ann in coco_data["annotations"]:
            img_id = ann["image_id"]
            if img_id not in img_id_to_info:
                continue
            img_info = img_id_to_info[img_id]
            file_name = img_info["file_name"]
            stem = Path(file_name).stem.lower()
            
            # coco 的 bbox 是 [xmin, ymin, width, height]
            bbox = ann.get("bbox")
            category_id = ann.get("category_id")
            if not bbox or category_id is None:
                continue
            
            if stem not in img_stem_to_annos:
                img_stem_to_annos[stem] = []
            img_stem_to_annos[stem].append({
                "category_id": category_id,
                "bbox": bbox, # [xmin, ymin, w, h]
                "img_w": img_info.get("width", 0),
                "img_h": img_info.get("height", 0),
            })
            
        result = {}
        for stem, annos in img_stem_to_annos.items():
            result[stem] = (annos, id_to_class)
        return result
    except Exception as e:
        logger.debug(f"尝试加载 COCO JSON 失败 {json_path}: {e}")
        return {}


def scan_dataset(root_dir: Path) -> Tuple[List[Dict[str, Any]], List[Path], Dict[int, str]]:
    """扫描指定目录下的正样本及负样本。
    
    正样本返回值字典格式:
    {
        "img_path": Path,
        "label_path": Path | None,
        "format": "YOLO" | "VOC" | "COCO",
        "bboxes": list[tuple[str | int, float, float, float, float]], # [class_id_or_name, xmin, ymin, xmax, ymax] 绝对坐标
        "img_w": int,
        "img_h": int,
    }
    """
    logger.info(f"开始扫描目录: {root_dir}")
    
    # 1. 递归找到所有图片
    all_img_paths: List[Path] = []
    for ext in SUPPORTED_IMAGE_EXTS:
        all_img_paths.extend(root_dir.rglob(f"*{ext}"))
        all_img_paths.extend(root_dir.rglob(f"*{ext.upper()}"))
    all_img_paths = sorted(list(set(all_img_paths)))
    
    # 2. 检查是否有负样本图片 (祖先目录以 background_ 开头)
    neg_images: List[Path] = []
    pos_candidate_imgs: List[Path] = []
    for img_p in all_img_paths:
        is_neg = False
        for p in img_p.parents:
            if p.name.startswith("background_"):
                is_neg = True
                break
        if is_neg:
            neg_images.append(img_p)
        else:
            pos_candidate_imgs.append(img_p)
            
    # 3. 寻找潜在的 XML, TXT, JSON 标注文件
    xml_dict: Dict[str, Path] = {}
    for p in root_dir.rglob("*.xml"):
        xml_dict[p.stem.lower()] = p
        
    txt_dict: Dict[str, Path] = {}
    for p in root_dir.rglob("*.txt"):
        if p.name.lower() == "classes.txt":
            continue
        txt_dict[p.stem.lower()] = p
        
    # 查找 COCO JSON
    coco_mappings: Dict[str, Tuple[List[Dict[str, Any]], Dict[int, str]]] = {}
    for p in root_dir.rglob("*.json"):
        mapping = load_coco_annotations(p)
        if mapping:
            coco_mappings.update(mapping)
            logger.info(f"成功载入 COCO 标注文件: {p}")
            
    # 尝试加载 classes.txt 映射
    classes_txt_map = {}
    classes_files = list(root_dir.glob("classes.txt")) + list(root_dir.rglob("classes.txt"))
    if classes_files:
        try:
            with open(classes_files[0], "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
                for idx, name in enumerate(lines):
                    classes_txt_map[idx] = name
            logger.info(f"读取到类别映射 classes.txt: {classes_txt_map}")
        except Exception as e:
            logger.debug(f"尝试读取 classes.txt 失败: {e}")
            
    # 尝试从 data.yaml 读取 mapping
    yaml_files = list(root_dir.glob("*.yaml")) + list(root_dir.glob("*.yml"))
    for yf in yaml_files:
        try:
            with open(yf, "r", encoding="utf-8") as f:
                yml_data = yaml.safe_load(f)
            if isinstance(yml_data, dict) and "names" in yml_data:
                names_val = yml_data["names"]
                if isinstance(names_val, list):
                    for i, n in enumerate(names_val):
                        classes_txt_map[i] = n
                elif isinstance(names_val, dict):
                    for k, v in names_val.items():
                        classes_txt_map[int(k)] = v
                logger.info(f"读取到类别映射 YAML: {classes_txt_map}")
                break
        except Exception:
            pass
            
    # 4. 配对正样本
    pos_samples: List[Dict[str, Any]] = []
    
    # 统计汇总 COCO 的类别
    id_to_class: Dict[int, str] = {}
    
    for img_path in pos_candidate_imgs:
        stem_lower = img_path.stem.lower()
        
        # A. 优先 COCO 配对
        if stem_lower in coco_mappings:
            bbox_list, coco_classes = coco_mappings[stem_lower]
            id_to_class.update(coco_classes)
            # 解析 bbox
            bboxes = []
            img_w, img_h = 0, 0
            for item in bbox_list:
                cat_id = item["category_id"]
                bx = item["bbox"] # [xmin, ymin, w, h]
                img_w = item["img_w"]
                img_h = item["img_h"]
                # 转换到 [cls, xmin, ymin, xmax, ymax]
                bboxes.append((cat_id, bx[0], bx[1], bx[0] + bx[2], bx[1] + bx[3]))
            
            # 若宽高缺失，读取图片
            if img_w <= 0 or img_h <= 0:
                try:
                    with Image.open(img_path) as pil_img:
                        img_w, img_h = pil_img.size
                except Exception:
                    img_w, img_h = 640, 640
                    
            if bboxes:
                pos_samples.append({
                    "img_path": img_path,
                    "label_path": None,
                    "format": "COCO",
                    "bboxes": bboxes,
                    "img_w": img_w,
                    "img_h": img_h,
                })
            else:
                neg_images.append(img_path)
            
        # B. 其次 VOC 配对
        elif stem_lower in xml_dict:
            xml_path = xml_dict[stem_lower]
            try:
                width, height, objects = parse_voc_file(xml_path)
                if width <= 0 or height <= 0:
                    with Image.open(img_path) as pil_img:
                        width, height = pil_img.size
                
                # objects 为 (class_name, xmin, ymin, xmax, ymax)
                if objects:
                    pos_samples.append({
                        "img_path": img_path,
                        "label_path": xml_path,
                        "format": "VOC",
                        "bboxes": objects,
                        "img_w": width,
                        "img_h": height,
                    })
                else:
                    neg_images.append(img_path)
            except Exception as e:
                logger.warning(f"解析 XML 失败 {xml_path}: {e}")
                
        # C. 再次 YOLO TXT 配对
        elif stem_lower in txt_dict:
            txt_path = txt_dict[stem_lower]
            try:
                # 读取图像尺寸
                with Image.open(img_path) as pil_img:
                    width, height = pil_img.size
                    
                bboxes = []
                with open(txt_path, "r", encoding="utf-8") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) >= 5:
                            try:
                                cls_id = int(parts[0])
                                # 相对坐标 xywhn
                                xc = float(parts[1])
                                yc = float(parts[2])
                                w = float(parts[3])
                                h = float(parts[4])
                                # 还原为绝对 xmin, ymin, xmax, ymax
                                xmin = (xc - w / 2) * width
                                ymin = (yc - h / 2) * height
                                xmax = (xc + w / 2) * width
                                ymax = (yc + h / 2) * height
                                bboxes.append((cls_id, xmin, ymin, xmax, ymax))
                            except ValueError:
                                continue
                if bboxes:
                    pos_samples.append({
                        "img_path": img_path,
                        "label_path": txt_path,
                        "format": "YOLO",
                        "bboxes": bboxes,
                        "img_w": width,
                        "img_h": height,
                    })
                else:
                    neg_images.append(img_path)
            except Exception as e:
                logger.warning(f"解析 YOLO TXT 失败 {txt_path}: {e}")
                
        else:
            logger.info(f"图片未配对到标注，自动归入背景负样本: {img_path}")
            neg_images.append(img_path)
            
    # 合并 classes_txt_map 到 id_to_class
    for k, v in classes_txt_map.items():
        if k not in id_to_class:
            id_to_class[k] = v
            
    logger.info(f"目录 {root_dir} 解析完成: 正样本对={len(pos_samples)}, 负样本={len(neg_images)}")
    return pos_samples, neg_images, id_to_class


def preprocess_train_dataset(
    data_dir: str,
    old_data_dir: str | None = None,
    new_sample_rate: float = 1.0,
    old_sample_rate: float = 1.0,
    new_ratio_min: float = 0.1,
    neg_ratio: float = 0.1,
    dest_dir: str | None = None,
) -> Path:
    """自适应预处理并将数据集规整混合至 dest_dir，生成 data.yaml 与分布报告。
    
    返回:
        生成的 data.yaml 的绝对路径
    """
    logger.info("=" * 60)
    logger.info("4estDS 模型训练数据集加工流程启动...")
    logger.info(f"输入数据集(新): {data_dir}")
    if old_data_dir:
        logger.info(f"输入数据集(旧): {old_data_dir}")
    logger.info(f"参数: new_sample_rate={new_sample_rate:.0%}, old_sample_rate={old_sample_rate:.0%}")
    logger.info(f"参数: new_ratio_min={new_ratio_min:.0%}, neg_ratio={neg_ratio:.0%}")
    logger.info("=" * 60)

    # 规范化输出目标
    if dest_dir is None:
        try:
            dest_dir = paths.run_dir() / "dataset"
        except Exception:
            dest_dir = paths.subdir("cache") / "temp_train_dataset"
    
    dest_path = Path(dest_dir).resolve()
    # 彻底清理或重构目录
    if dest_path.exists():
        logger.warning(f"目标目录已存在，正在清理: {dest_path}")
        shutil.rmtree(dest_path)
    dest_path.mkdir(parents=True, exist_ok=True)

    # 初始化子目录明细统计字典
    # key: (rel_dir_str, dataset_type)
    # val: {"pos_scan": 0, "neg_scan": 0, "pos_final": 0, "neg_final": 0}
    subdirs_stats: Dict[Tuple[str, str], Dict[str, int]] = {}

    new_root = Path(data_dir).resolve()
    old_root = Path(old_data_dir).resolve() if old_data_dir else None

    def get_rel_dir(path: Path, root: Path) -> str:
        try:
            return str(path.parent.relative_to(root))
        except Exception:
            return "."

    # 1. 扫描两个目录
    new_pos, new_neg, new_id_to_class = scan_dataset(new_root)
    
    old_pos, old_neg, old_id_to_class = [], [], {}
    if old_root:
        old_pos, old_neg, old_id_to_class = scan_dataset(old_root)

    # 填充扫描阶段数据
    for s in new_pos:
        rel = get_rel_dir(s["img_path"], new_root)
        key = (rel, "new")
        if key not in subdirs_stats:
            subdirs_stats[key] = {"pos_scan": 0, "neg_scan": 0, "pos_final": 0, "neg_final": 0}
        subdirs_stats[key]["pos_scan"] += 1

    for p in new_neg:
        rel = get_rel_dir(p, new_root)
        key = (rel, "new")
        if key not in subdirs_stats:
            subdirs_stats[key] = {"pos_scan": 0, "neg_scan": 0, "pos_final": 0, "neg_final": 0}
        subdirs_stats[key]["neg_scan"] += 1

    if old_root:
        for s in old_pos:
            rel = get_rel_dir(s["img_path"], old_root)
            key = (rel, "old")
            if key not in subdirs_stats:
                subdirs_stats[key] = {"pos_scan": 0, "neg_scan": 0, "pos_final": 0, "neg_final": 0}
            subdirs_stats[key]["pos_scan"] += 1

        for p in old_neg:
            rel = get_rel_dir(p, old_root)
            key = (rel, "old")
            if key not in subdirs_stats:
                subdirs_stats[key] = {"pos_scan": 0, "neg_scan": 0, "pos_final": 0, "neg_final": 0}
            subdirs_stats[key]["neg_scan"] += 1


    # 2. 确定全局类别映射列表 (去重并排序)
    all_class_names: Set[str] = set()
    
    def get_real_name(cls_val: Any, mapping: Dict[int, str]) -> str:
        if isinstance(cls_val, str):
            return cls_val
        return mapping.get(cls_val, f"class_{cls_val}")

    for s in new_pos:
        for bbox in s["bboxes"]:
            all_class_names.add(get_real_name(bbox[0], new_id_to_class))
            
    for s in old_pos:
        for bbox in s["bboxes"]:
            all_class_names.add(get_real_name(bbox[0], old_id_to_class))
            
    global_classes = sorted(list(all_class_names))
    if not global_classes:
        global_classes = ["tree"] # 兜底
        
    class_to_id = {name: idx for idx, name in enumerate(global_classes)}
    id_to_class = {idx: name for idx, name in enumerate(global_classes)}
    logger.info(f"统一全局类别列表: {global_classes}")

    # 3. 抽样阶段
    random.seed(42)
    
    # 新样本抽样
    new_sampled_count = int(len(new_pos) * new_sample_rate)
    new_pos_sampled = random.sample(new_pos, new_sampled_count) if new_pos else []
    
    # 旧样本抽样
    old_sampled_count = int(len(old_pos) * old_sample_rate)
    old_pos_sampled = random.sample(old_pos, old_sampled_count) if old_pos else []

    # 4. 新旧样本混合与过采样
    final_pos_sampled = []
    
    n_new = len(new_pos_sampled)
    n_old = len(old_pos_sampled)
    
    if old_data_dir and (n_new + n_old) > 0:
        current_new_ratio = n_new / (n_new + n_old)
        if current_new_ratio < new_ratio_min:
            target_new_count = int(n_old * new_ratio_min / (1 - new_ratio_min))
            diff = target_new_count - n_new
            logger.info(f"当前新样本占比为 {current_new_ratio:.1%}, 低于阈值 {new_ratio_min:.1%}。")
            logger.info(f"需要过采样新样本，增加数量: {diff} 个")
            
            extra_new = [random.choice(new_pos_sampled) for _ in range(diff)]
            
            for idx, s in enumerate(new_pos_sampled):
                final_pos_sampled.append((s, "new", 0))
            for idx, s in enumerate(extra_new):
                final_pos_sampled.append((s, "new", idx + 1))
        else:
            logger.info(f"新样本占比为 {current_new_ratio:.1%}, 符合 >= {new_ratio_min:.1%} 设定，全量采纳。")
            for s in new_pos_sampled:
                final_pos_sampled.append((s, "new", 0))
        
        for s in old_pos_sampled:
            final_pos_sampled.append((s, "old", 0))
    else:
        for s in new_pos_sampled:
            final_pos_sampled.append((s, "new", 0))

    # 5. 负样本采样
    total_pos_count = len(final_pos_sampled)
    if total_pos_count == 0:
        logger.warning("采纳的正样本数量为 0！")
        
    target_neg_count = math.ceil(total_pos_count * neg_ratio / (1 - neg_ratio)) if neg_ratio < 1.0 else 0
    
    def group_negatives_by_dir(neg_list: List[Path]) -> Dict[Path, List[Path]]:
        groups = {}
        for p in neg_list:
            bg_dir = None
            for parent in p.parents:
                if parent.name.startswith("background_"):
                    bg_dir = parent
                    break
            if bg_dir is None:
                bg_dir = p.parent # 兜底
            if bg_dir not in groups:
                groups[bg_dir] = []
            groups[bg_dir].append(p)
        return groups

    new_neg_sampled = random.sample(new_neg, int(len(new_neg) * new_sample_rate)) if new_neg else []
    old_neg_sampled = random.sample(old_neg, int(len(old_neg) * old_sample_rate)) if old_neg else []
    
    all_neg_pool = new_neg_sampled + old_neg_sampled
    final_neg_sampled: List[Tuple[Path, str]] = []
    
    if target_neg_count > 0 and all_neg_pool:
        neg_groups = group_negatives_by_dir(all_neg_pool)
        num_groups = len(neg_groups)
        logger.info(f"检测到存在 {num_groups} 个负样本子目录。目标负样本数: {target_neg_count}")
        
        quota_per_group = target_neg_count // num_groups
        surplus_pool = target_neg_count % num_groups
        
        group_candidates = {}
        for bg_dir, imgs in neg_groups.items():
            random.shuffle(imgs)
            new_set = set(new_neg)
            
            sampled_this_round = []
            if len(imgs) <= quota_per_group:
                sampled_this_round = imgs
                surplus_pool += (quota_per_group - len(imgs))
            else:
                sampled_this_round = imgs[:quota_per_group]
                group_candidates[bg_dir] = imgs[quota_per_group:]
                
            for p in sampled_this_round:
                origin = "new" if p in new_set else "old"
                final_neg_sampled.append((p, origin))
                
        if surplus_pool > 0 and group_candidates:
            remaining_candidates = []
            for bg_dir, imgs in group_candidates.items():
                new_set = set(new_neg)
                for p in imgs:
                    origin = "new" if p in new_set else "old"
                    remaining_candidates.append((p, origin))
            
            random.shuffle(remaining_candidates)
            take_num = min(surplus_pool, len(remaining_candidates))
            final_neg_sampled.extend(remaining_candidates[:take_num])
            
        logger.info(f"最终采纳负样本图片数量: {len(final_neg_sampled)}/{target_neg_count}")
    elif target_neg_count > 0:
        logger.info("未检测到任何以 background_ 开头的子目录，不引入负样本。")

    # 6. 数据集划分与规整写入 (8:2 随机拆分)
    all_packages = []
    for s, origin, dup_idx in final_pos_sampled:
        all_packages.append((s, origin, dup_idx))
    for p, origin in final_neg_sampled:
        all_packages.append((p, origin, "neg"))
        
    random.shuffle(all_packages)
    split_idx = int(len(all_packages) * 0.8)
    train_packages = all_packages[:split_idx]
    val_packages = all_packages[split_idx:]
    
    report_stats = {
        "train": {"pos": 0, "neg": 0, "boxes": 0},
        "val": {"pos": 0, "neg": 0, "boxes": 0},
        "new": {"pos": 0, "neg": 0, "boxes": 0},
        "old": {"pos": 0, "neg": 0, "boxes": 0},
        "class_boxes": {name: 0 for name in global_classes},
        "box_widths": [],
        "box_equivalent_widths": [],
    }

    # 执行文件规整与写入
    for split_name, packages in [("train", train_packages), ("val", val_packages)]:
        img_out_dir = dest_path / "images" / split_name
        lbl_out_dir = dest_path / "labels" / split_name
        img_out_dir.mkdir(parents=True, exist_ok=True)
        lbl_out_dir.mkdir(parents=True, exist_ok=True)
        
        for pkg in packages:
            origin = pkg[1]
            is_neg = (pkg[2] == "neg")
            
            if not is_neg:
                s, dup_idx = pkg[0], pkg[2]
                img_path = s["img_path"]
                
                # 记录采纳统计
                rel = get_rel_dir(img_path, new_root if origin == "new" else old_root)
                key = (rel, origin)
                if key not in subdirs_stats:
                    subdirs_stats[key] = {"pos_scan": 0, "neg_scan": 0, "pos_final": 0, "neg_final": 0}
                subdirs_stats[key]["pos_final"] += 1

                
                # 平铺命名，防多级目录重名冲突
                rel_parts = img_path.parent.relative_to(Path(data_dir if origin == "new" else old_data_dir).resolve()).parts
                dir_prefix = "_".join(rel_parts) + "_" if rel_parts else ""
                
                dup_suffix = f"_dup{dup_idx}" if dup_idx > 0 else ""
                unique_name = f"{origin}_{dir_prefix}{img_path.stem}{dup_suffix}"
                
                dest_img_path = img_out_dir / f"{unique_name}{img_path.suffix}"
                process_and_link_image(img_path, dest_img_path)
                
                dest_txt_path = lbl_out_dir / f"{unique_name}.txt"
                
                img_w = s["img_w"]
                img_h = s["img_h"]
                
                bboxes_to_write = []
                for box in s["bboxes"]:
                    cls_val, xmin, ymin, xmax, ymax = box
                    
                    cls_name = get_real_name(cls_val, new_id_to_class if origin == "new" else old_id_to_class)
                    global_class_id = class_to_id.get(cls_name, 0)
                    
                    xmin = max(0.0, min(float(xmin), float(img_w)))
                    ymin = max(0.0, min(float(ymin), float(img_h)))
                    xmax = max(0.0, min(float(xmax), float(img_w)))
                    ymax = max(0.0, min(float(ymax), float(img_h)))
                    
                    bw = xmax - xmin
                    bh = ymax - ymin
                    if bw <= 0 or bh <= 0:
                        continue
                        
                    x_center = (xmin + bw / 2) / img_w
                    y_center = (ymin + bh / 2) / img_h
                    w_norm = bw / img_w
                    h_norm = bh / img_h
                    
                    bboxes_to_write.append((global_class_id, x_center, y_center, w_norm, h_norm))
                    
                    report_stats["class_boxes"][cls_name] += 1
                    report_stats["box_widths"].append(bw)
                    report_stats["box_equivalent_widths"].append(math.sqrt(bw * bh))
                    report_stats[split_name]["boxes"] += 1
                    report_stats[origin]["boxes"] += 1
                    
                with open(dest_txt_path, "w", encoding="utf-8") as f:
                    for item in bboxes_to_write:
                        f.write(f"{item[0]} {item[1]:.6f} {item[2]:.6f} {item[3]:.6f} {item[4]:.6f}\n")
                        
                report_stats[split_name]["pos"] += 1
                report_stats[origin]["pos"] += 1
                
            else:
                img_path = pkg[0]
                
                # 记录采纳统计
                rel = get_rel_dir(img_path, new_root if origin == "new" else old_root)
                key = (rel, origin)
                if key not in subdirs_stats:
                    subdirs_stats[key] = {"pos_scan": 0, "neg_scan": 0, "pos_final": 0, "neg_final": 0}
                subdirs_stats[key]["neg_final"] += 1

                
                rel_parts = img_path.parent.relative_to(Path(data_dir if origin == "new" else old_data_dir).resolve()).parts
                dir_prefix = "_".join(rel_parts) + "_" if rel_parts else ""
                unique_name = f"{origin}_{dir_prefix}{img_path.stem}"
                
                dest_img_path = img_out_dir / f"{unique_name}{img_path.suffix}"
                process_and_link_image(img_path, dest_img_path)
                
                dest_txt_path = lbl_out_dir / f"{unique_name}.txt"
                with open(dest_txt_path, "w", encoding="utf-8") as f:
                    pass
                    
                report_stats[split_name]["neg"] += 1
                report_stats[origin]["neg"] += 1

    # 7. 绘图与分布报告生成
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        
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
        plt.rcParams['font.sans-serif'] = found_fonts + font_candidates + ['DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False
        
        widths = report_stats["box_widths"]
        eq_widths = report_stats["box_equivalent_widths"]
        
        if widths:
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
            
            ax1.hist(widths, bins=30, color="#1976d2", edgecolor="white", alpha=0.8)
            ax1.set_title("目标框宽度分布直方图")
            ax1.set_xlabel("宽度 (像素)")
            ax1.set_ylabel("频数")
            
            ax2.hist(eq_widths, bins=30, color="#2e7d32", edgecolor="white", alpha=0.8)
            ax2.set_title("目标框等效宽度分布直方图 ($\sqrt{w \\times h}$)")
            ax2.set_xlabel("等效宽度 (像素)")
            ax2.set_ylabel("频数")
            
            fig.tight_layout()
            chart_path = dest_path / "distribution_report.png"
            fig.savefig(chart_path, dpi=150)
            plt.close(fig)
            logger.info(f"成功生成分布直方图: {chart_path}")
        else:
            logger.warning("正样本中未发现任何有效目标框，跳过直方图生成。")
            
    except Exception as e:
        logger.warning(f"使用 matplotlib 绘制直方图失败，已跳过。原因: {e}")

    # 导出 markdown 报告
    report_md_path = dest_path / "distribution_report.md"
    try:
        with open(report_md_path, "w", encoding="utf-8") as f:
            f.write("# 训练集数据分布报告\n\n")
            f.write(f"本报告统计基于最终采纳并规整混合后的图像集合。\n\n")
            
            f.write("## 1. 数据集基本统计 (划分与对比)\n\n")
            f.write("| 统计指标 | 训练集 (Train) | 验证集 (Val) | 新数据集 (New) | 旧数据集 (Old) | 合计 (Total) |\n")
            f.write("| --- | --- | --- | --- | --- | --- |\n")
            
            tr_p, tr_n = report_stats["train"]["pos"], report_stats["train"]["neg"]
            va_p, va_n = report_stats["val"]["pos"], report_stats["val"]["neg"]
            nw_p, nw_n = report_stats["new"]["pos"], report_stats["new"]["neg"]
            ol_p, ol_n = report_stats["old"]["pos"], report_stats["old"]["neg"]
            
            tot_p = tr_p + va_p
            tot_n = tr_n + va_n
            
            f.write(f"| 正样本图片数 | {tr_p} | {va_p} | {nw_p} | {ol_p} | {tot_p} |\n")
            f.write(f"| 负样本图片数 | {tr_n} | {va_n} | {nw_n} | {ol_n} | {tot_n} |\n")
            f.write(f"| 总图片数 | {tr_p + tr_n} | {va_p + va_n} | {nw_p + nw_n} | {ol_p + ol_n} | {tot_p + tot_n} |\n")
            
            tr_b, va_b = report_stats["train"]["boxes"], report_stats["val"]["boxes"]
            nw_b, ol_b = report_stats["new"]["boxes"], report_stats["old"]["boxes"]
            tot_b = tr_b + va_b
            
            f.write(f"| 总标注框数 | {tr_b} | {va_b} | {nw_b} | {ol_b} | {tot_b} |\n")
            
            avg_tr = f"{tr_b / (tr_p or 1):.2f}" if tr_p > 0 else "0.00"
            avg_va = f"{va_b / (va_p or 1):.2f}" if va_p > 0 else "0.00"
            avg_nw = f"{nw_b / (nw_p or 1):.2f}" if nw_p > 0 else "0.00"
            avg_ol = f"{ol_b / (ol_p or 1):.2f}" if ol_p > 0 else "0.00"
            avg_tot = f"{tot_b / (tot_p or 1):.2f}" if tot_p > 0 else "0.00"
            
            f.write(f"| 平均每张正样本框数 | {avg_tr} | {avg_va} | {avg_nw} | {avg_ol} | {avg_tot} |\n\n")
            
            f.write("## 2. 子目录明细数据统计\n\n")
            f.write("| 数据集类别 | 子目录名称 | 扫描正样本数 | 扫描负样本数 | 最终采纳正样本数 | 最终采纳负样本数 | 采纳率/占比说明 |\n")
            f.write("| --- | --- | --- | --- | --- | --- | --- |\n")
            for (rel_dir, origin), stats in sorted(subdirs_stats.items(), key=lambda x: (x[0][1], x[0][0])):
                origin_name = "新 (New)" if origin == "new" else "旧 (Old)"
                # 计算正样本采纳率/占比
                p_scan = stats["pos_scan"]
                p_final = stats["pos_final"]
                n_scan = stats["neg_scan"]
                n_final = stats["neg_final"]
                
                info = ""
                if origin == "new" and p_scan > 0:
                    info = f"正: {p_final}/{p_scan} ({p_final/p_scan:.1%})"
                    if p_final > p_scan:
                        info += " (过采样)"
                else:
                    info = f"正采纳率: {p_final/(p_scan or 1):.1%}"
                
                if n_scan > 0:
                    info += f" | 负: {n_final}/{n_scan} ({n_final/n_scan:.1%})"
                
                f.write(f"| {origin_name} | `{rel_dir}` | {p_scan} | {n_scan} | {p_final} | {n_final} | {info} |\n")
            f.write("\n")
            
            f.write("## 3. 类别分布统计\n\n")
            f.write("| 类别名称 | 标注框数量 | 框数量占比 |\n")
            f.write("| --- | --- | --- |\n")
            for name, count in report_stats["class_boxes"].items():
                ratio_str = f"{count / (tot_b or 1):.2%}" if tot_b > 0 else "0.0%"
                f.write(f"| {name} | {count} | {ratio_str} |\n")
            f.write("\n")
            
            f.write("## 3. 目标框尺度特征分布\n\n")
            widths = report_stats["box_widths"]
            eq_widths = report_stats["box_equivalent_widths"]
            if widths:
                f.write(f"- **平均目标宽度**: {sum(widths) / len(widths):.1f} 像素\n")
                f.write(f"- **平均等效宽度**: {sum(eq_widths) / len(eq_widths):.1f} 像素\n\n")
                f.write("### 尺度分布直方图\n\n")
                f.write("![尺度分布直方图](distribution_report.png)\n")
            else:
                f.write("未检测到有效目标框。\n")
                
        logger.info(f"分布报告 Markdown 已成功生成: {report_md_path}")
    except Exception as e:
        logger.error(f"写入分布报告 Markdown 失败: {e}")

    # 8. 写入 data.yaml 文件
    data_yaml_content = {
        "path": str(dest_path),
        "train": "images/train",
        "val": "images/val",
        "names": id_to_class
    }
    
    data_yaml_path = dest_path / "data.yaml"
    with open(data_yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data_yaml_content, f, allow_unicode=True, default_flow_style=False)
        
    logger.info(f"数据集校验与自适应规整成功，已自动生成训练描述文件: {data_yaml_path}")
    logger.debug(f"data.yaml 结构: {data_yaml_content}")
    
    return data_yaml_path
