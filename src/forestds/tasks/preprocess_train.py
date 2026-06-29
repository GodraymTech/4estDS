"""模型训练数据集自适应预处理与规整模块。

支持 YOLO, VOC, COCO 格式以及基于叶子节点与背景目录的结构化配对、负样本采样、
新旧数据集混合、过采样占比控制、8:2 随机划分，并调用报表生成模块进行大表画像输出。
"""
from __future__ import annotations

import logging
import random
import shutil
import os
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple, Set
from PIL import Image
import yaml

from forestds import paths
from forestds.utils.annotations import parse_voc_file, SUPPORTED_IMAGE_EXTS

logger = logging.getLogger("forestds")


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
    如果是多通道、RGBA、灰度等，转为 RGB 并存入目标，以防止 YOLO 训练报错。
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
    """加载 COCO 格式的标注 JSON 文件。"""
    try:
        import json
        with open(json_path, "r", encoding="utf-8") as f:
            coco_data = json.load(f)
            
        if not isinstance(coco_data, dict) or "images" not in coco_data or "annotations" not in coco_data:
            return {}
            
        id_to_class = {}
        if "categories" in coco_data:
            for cat in coco_data["categories"]:
                id_to_class[cat["id"]] = cat["name"]
                
        img_id_to_info = {}
        for img in coco_data["images"]:
            img_id_to_info[img["id"]] = img
            
        img_stem_to_annos = {}
        for ann in coco_data["annotations"]:
            img_id = ann["image_id"]
            if img_id not in img_id_to_info:
                continue
            img_info = img_id_to_info[img_id]
            file_name = img_info["file_name"]
            stem = Path(file_name).stem.lower()
            
            bbox = ann.get("bbox")
            category_id = ann.get("category_id")
            if not bbox or category_id is None:
                continue
            
            if stem not in img_stem_to_annos:
                img_stem_to_annos[stem] = []
            img_stem_to_annos[stem].append({
                "category_id": category_id,
                "bbox": bbox, 
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


def scan_dataset(root_dir: Path) -> Tuple[List[Dict[str, Any]], List[Tuple[Path, str]], Dict[int, str]]:
    """扫描指定目录下的叶子节点目录及背景目录，解析得到正负样本。
    
    正样本返回值字典格式:
    {
        "img_path": Path,
        "label_path": Path | None,
        "format": "YOLO" | "VOC" | "COCO",
        "bboxes": list[tuple[str | int, float, float, float, float]], 
        "img_w": int,
        "img_h": int,
        "node_name": str, 
    }
    负样本返回值格式: List[Tuple[图像物理路径, 所属子叶子节点或背景目录名]]
    """
    logger.info(f"👉👉 开始结构化扫描数据集目录: {root_dir}")
    
    node_dirs: List[Path] = []
    background_dirs: List[Path] = []
    
    def find_nodes(d: Path):
        if d.name.startswith("background_"):
            background_dirs.append(d)
            return
            
        has_xml = any(d.glob("*.xml"))
        has_json = any(d.glob("*.json"))
        has_txt = any(p.name.lower() != "classes.txt" for p in d.glob("*.txt"))
        
        has_img = False
        for ext in SUPPORTED_IMAGE_EXTS:
            if any(d.glob(f"*{ext}")) or any(d.glob(f"*{ext.upper()}")):
                has_img = True
                break
                
        has_yolo_sub = (d / "images").exists() or (d / "labels").exists()
        has_voc_sub = (d / "Annotations").exists() or (d / "JPEGImages").exists()
        
        if (has_img and (has_xml or has_json or has_txt)) or has_yolo_sub or has_voc_sub:
            node_dirs.append(d)
            return  
            
        for sub in d.iterdir():
            if sub.is_dir() and not sub.name.startswith("."):
                find_nodes(sub)
                
    if root_dir.exists() and root_dir.is_dir():
        find_nodes(root_dir)
        
    if not node_dirs and not background_dirs:
        node_dirs = [root_dir]
        
    logger.info(f"发现叶子节点目录: {len(node_dirs)} 个, 背景目录: {len(background_dirs)} 个")
    for nd in node_dirs:
        logger.info(f"  - 叶子: {nd.relative_to(root_dir) if nd != root_dir else '.'}")
    for bd in background_dirs:
        logger.info(f"  - 背景: {bd.relative_to(root_dir)}")

    pos_samples: List[Dict[str, Any]] = []
    neg_images: List[Tuple[Path, str]] = []
    
    # 局部高内聚解析各目录下的数据
    for nd in node_dirs:
        node_name = str(nd.relative_to(root_dir)) if nd != root_dir else "."
        logger.debug(f"正在解析叶子节点目录: {node_name}")
        
        local_class_map = {}
        classes_files = list(nd.glob("classes.txt")) + list(nd.rglob("classes.txt"))
        if classes_files:
            try:
                with open(classes_files[0], "r", encoding="utf-8") as f:
                    lines = [l.strip() for l in f if l.strip()]
                    for idx, name in enumerate(lines):
                        local_class_map[idx] = name
            except Exception:
                pass
                
        yaml_files = list(nd.glob("*.yaml")) + list(nd.glob("*.yml")) + list(nd.rglob("*.yaml"))
        for yf in yaml_files:
            try:
                with open(yf, "r", encoding="utf-8") as f:
                    yml_data = yaml.safe_load(f)
                if isinstance(yml_data, dict) and "names" in yml_data:
                    names_val = yml_data["names"]
                    if isinstance(names_val, list):
                        for i, n in enumerate(names_val):
                            local_class_map[i] = n
                    elif isinstance(names_val, dict):
                        for k, v in names_val.items():
                            local_class_map[int(k)] = v
                    break
            except Exception:
                pass
                
        node_imgs: List[Path] = []
        for ext in SUPPORTED_IMAGE_EXTS:
            node_imgs.extend(nd.rglob(f"*{ext}"))
            node_imgs.extend(nd.rglob(f"*{ext.upper()}"))
        node_imgs = sorted(list(set(node_imgs)))
        
        valid_node_imgs = []
        for img in node_imgs:
            is_in_bg = False
            for bg in background_dirs:
                try:
                    img.relative_to(bg)
                    is_in_bg = True
                    break
                except ValueError:
                    pass
            if not is_in_bg:
                valid_node_imgs.append(img)
                
        xml_dict: Dict[str, Path] = {}
        for p in nd.rglob("*.xml"):
            xml_dict[p.name.lower().split(".")[0]] = p
            
        txt_dict: Dict[str, Path] = {}
        for p in nd.rglob("*.txt"):
            if p.name.lower() == "classes.txt":
                continue
            txt_dict[p.name.lower().split(".")[0]] = p
            
        coco_mappings = {}
        for p in nd.rglob("*.json"):
            mapping = load_coco_annotations(p)
            if mapping:
                coco_mappings.update(mapping)
                
        for img_path in valid_node_imgs:
            stem_lower = img_path.name.lower().split(".")[0]
            
            # COCO 配对
            if stem_lower in coco_mappings:
                bbox_list, coco_classes = coco_mappings[stem_lower]
                local_map_combined = local_class_map.copy()
                local_map_combined.update(coco_classes)
                
                bboxes = []
                img_w, img_h = 0, 0
                for item in bbox_list:
                    cat_id = item["category_id"]
                    cls_name = local_map_combined.get(cat_id, f"class_{cat_id}")
                    bx = item["bbox"] 
                    img_w = item["img_w"]
                    img_h = item["img_h"]
                    bboxes.append((cls_name, bx[0], bx[1], bx[0] + bx[2], bx[1] + bx[3]))
                    
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
                        "node_name": node_name,
                    })
                else:
                    neg_images.append((img_path, node_name))
                    
            # VOC 配对
            elif stem_lower in xml_dict:
                xml_path = xml_dict[stem_lower]
                try:
                    width, height, objects = parse_voc_file(xml_path)
                    if width <= 0 or height <= 0:
                        try:
                            with Image.open(img_path) as pil_img:
                                width, height = pil_img.size
                        except Exception:
                            width, height = 640, 640
                    bboxes = []
                    for obj in objects:
                        bboxes.append((obj[0], obj[1], obj[2], obj[3], obj[4]))
                    if bboxes:
                        pos_samples.append({
                            "img_path": img_path,
                            "label_path": xml_path,
                            "format": "VOC",
                            "bboxes": bboxes,
                            "img_w": width,
                            "img_h": height,
                            "node_name": node_name,
                        })
                    else:
                        neg_images.append((img_path, node_name))
                except Exception as e:
                    logger.debug(f"解析 VOC 失败 {xml_path}: {e}")
                    
            # YOLO 配对
            elif stem_lower in txt_dict:
                txt_path = txt_dict[stem_lower]
                try:
                    with Image.open(img_path) as pil_img:
                        width, height = pil_img.size
                    bboxes = []
                    with open(txt_path, "r", encoding="utf-8") as f:
                        for line in f:
                            parts = line.strip().split()
                            if len(parts) >= 5:
                                try:
                                    class_id = int(parts[0])
                                except ValueError:
                                    class_id = parts[0]
                                    
                                if isinstance(class_id, int):
                                    cls_name = local_class_map.get(class_id, f"class_{class_id}")
                                else:
                                    cls_name = class_id
                                    
                                x_c, y_c, w, h = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
                                xmin = (x_c - w / 2) * width
                                ymin = (y_c - h / 2) * height
                                xmax = (x_c + w / 2) * width
                                ymax = (y_c + h / 2) * height
                                bboxes.append((cls_name, xmin, ymin, xmax, ymax))
                    if bboxes:
                        pos_samples.append({
                            "img_path": img_path,
                            "label_path": txt_path,
                            "format": "YOLO",
                            "bboxes": bboxes,
                            "img_w": width,
                            "img_h": height,
                            "node_name": node_name,
                        })
                    else:
                        neg_images.append((img_path, node_name))
                except Exception as e:
                    logger.debug(f"解析 YOLO 失败 {txt_path}: {e}")
                    
            else:
                neg_images.append((img_path, node_name))

    # 解析背景目录 (100% 负样本)
    for bd in background_dirs:
        node_name = str(bd.relative_to(root_dir))
        logger.debug(f"正在解析背景负样本目录: {node_name}")
        bd_imgs: List[Path] = []
        for ext in SUPPORTED_IMAGE_EXTS:
            bd_imgs.extend(bd.rglob(f"*{ext}"))
            bd_imgs.extend(bd.rglob(f"*{ext.upper()}"))
        bd_imgs = sorted(list(set(bd_imgs)))
        for img_p in bd_imgs:
            neg_images.append((img_p, node_name))

    # 汇总去重全局类别映射
    all_classes_set = set()
    for s in pos_samples:
        for bbox in s["bboxes"]:
            all_classes_set.add(bbox[0])
    global_classes = sorted(list(all_classes_set))
    global_id_to_class = {idx: name for idx, name in enumerate(global_classes)}
    
    logger.info(
        f"目录扫描解析完成: 扫描到正样本图像 {len(pos_samples)} 张，"
        f"负样本图像 {len(neg_images)} 张，统一类别列表: {global_classes}"
    )
    
    return pos_samples, neg_images, global_id_to_class


def preprocess_train_dataset(
    data_dir: str,
    old_data_dir: str | None = None,
    new_sample_rate: float = 1.0,
    old_sample_rate: float = 1.0,
    new_ratio_min: float = 0.1,
    neg_ratio: float = 0.1,
    dest_dir: str | None = None,
) -> Path:
    """自适应预处理并将数据集规整混合至 dest_dir，生成 data.yaml 与分布报告。"""
    logger.info("=" * 60)
    logger.info("训练集预处理启动...")
    logger.info(f"输入数据集(新/增量): {data_dir}")
    if old_data_dir:
        logger.info(f"输入数据集(旧/主集): {old_data_dir}")
    logger.info(f"参数: new_sample_rate={new_sample_rate:.0%}, old_sample_rate={old_sample_rate:.0%}")
    logger.info(f"参数: new_ratio_min={new_ratio_min:.0%}, neg_ratio={neg_ratio:.0%}")
    logger.info("=" * 60)

    # 准备目标文件夹
    if dest_dir is None:
        try:
            dest_dir = paths.run_dir() / "dataset"
        except Exception:
            dest_dir = paths.subdir("cache") / "temp_train_dataset"
    
    dest_path = Path(dest_dir).resolve()
    if dest_path.exists():
        logger.warning(f"目标目录已存在，正在清理: {dest_path}")
        shutil.rmtree(dest_path)
    dest_path.mkdir(parents=True, exist_ok=True)

    new_root = Path(data_dir).resolve()
    old_root = Path(old_data_dir).resolve() if old_data_dir else None

    # 1. 扫描新旧目录
    new_pos, new_neg, new_id_to_class = scan_dataset(new_root)
    old_pos, old_neg, old_id_to_class = [], [], {}
    if old_root:
        old_pos, old_neg, old_id_to_class = scan_dataset(old_root)

    # 2. 建立全局类别映射
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
        global_classes = ["tree"]
        
    class_to_id = {name: idx for idx, name in enumerate(global_classes)}
    id_to_class = {idx: name for idx, name in enumerate(global_classes)}

    # 3. 抽样与重采样占比处理
    random.seed(42)
    new_sampled_count = int(len(new_pos) * new_sample_rate)
    new_pos_sampled = random.sample(new_pos, new_sampled_count) if new_pos else []
    
    old_sampled_count = int(len(old_pos) * old_sample_rate)
    old_pos_sampled = random.sample(old_pos, old_sampled_count) if old_pos else []

    final_pos_sampled = []
    n_new = len(new_pos_sampled)
    n_old = len(old_pos_sampled)
    
    if old_root and (n_new + n_old) > 0:
        current_new_ratio = n_new / (n_new + n_old)
        if current_new_ratio < new_ratio_min:
            target_new_count = int(n_old * new_ratio_min / (1 - new_ratio_min))
            diff = target_new_count - n_new
            logger.info(f"当前新样本占比为 {current_new_ratio:.1%}, 低于红线 {new_ratio_min:.1%}, 需过采样新样本 {diff} 个")
            
            extra_new = [random.choice(new_pos_sampled) for _ in range(diff)]
            for s in new_pos_sampled:
                final_pos_sampled.append((s, "new", 0))
            for idx, s in enumerate(extra_new):
                final_pos_sampled.append((s, "new", idx + 1))
        else:
            logger.info(f"新样本占比为 {current_new_ratio:.1%}, 满足设定比例 >= {new_ratio_min:.1%}")
            for s in new_pos_sampled:
                final_pos_sampled.append((s, "new", 0))
        for s in old_pos_sampled:
            final_pos_sampled.append((s, "old", 0))
    else:
        for s in new_pos_sampled:
            final_pos_sampled.append((s, "new", 0))

    # 4. 负样本采样逻辑深度重构 (背景全采 ➔ 叶子节点按正比例无过采样找齐)
    total_pos_count = len(final_pos_sampled)
    target_neg_count = math.ceil(total_pos_count * neg_ratio / (1 - neg_ratio)) if neg_ratio < 1.0 else 0

    # 建立负样本池归档
    bg_neg_pools: Dict[str, List[Tuple[Path, str]]] = {}
    leaf_neg_pools: Dict[str, List[Tuple[Path, str]]] = {}
    
    new_neg_sets = set(img_p for img_p, _ in new_neg)
    
    for img_p, belong in new_neg + old_neg:
        origin = "new" if img_p in new_neg_sets else "old"
        if belong.startswith("background_"):
            bg_neg_pools.setdefault(belong, []).append((img_p, origin))
        else:
            leaf_neg_pools.setdefault(belong, []).append((img_p, origin))

    final_neg_sampled: List[Tuple[Path, str, str]] = [] # (img_path, origin, belong_name)

    # a. 背景负样本底片全选全采
    logger.info("👉 开始第一阶段：纯背景负样本目录底片无条件全量采纳...")
    for bg_name, items in bg_neg_pools.items():
        for img_p, origin in items:
            final_neg_sampled.append((img_p, origin, bg_name))
            
    total_bg_collected = len(final_neg_sampled)
    global_debt = target_neg_count - total_bg_collected

    # b. 从叶子节点的负样本池中按比例找齐
    if global_debt > 0:
        logger.info(f"第一阶段采纳背景图 {total_bg_collected} 张。全局负样本仍存在债务 {global_debt} 张，")
        logger.info("👉 进入第二阶段：从叶子负样本池中按比例找齐...")
        
        # 统计每个叶子节点采纳的正样本数量
        leaf_pos_counts: Dict[str, int] = {}
        for s, _, _ in final_pos_sampled:
            leaf_pos_counts[s["node_name"]] = leaf_pos_counts.get(s["node_name"], 0) + 1
            
        leaf_assigned: Dict[str, int] = {}
        sorted_leaves = sorted(leaf_pos_counts.keys(), key=lambda k: leaf_pos_counts[k], reverse=True)
        for leaf_name in sorted_leaves:
            pos_cnt = leaf_pos_counts[leaf_name]
            share = math.ceil(global_debt * (pos_cnt / total_pos_count))
            leaf_assigned[leaf_name] = share
            
        secondary_debt = 0
        leaf_remaining_candidates: Dict[str, List[Tuple[Path, str]]] = {}
        sampled_leaf_neg = []
        
        # 局部无过采样抽取
        for leaf_name, assign_cnt in leaf_assigned.items():
            pool = leaf_neg_pools.get(leaf_name, [])
            random.shuffle(pool)
            
            if len(pool) >= assign_cnt:
                sampled = pool[:assign_cnt]
                leaf_remaining_candidates[leaf_name] = pool[assign_cnt:]
                for img_p, origin in sampled:
                    sampled_leaf_neg.append((img_p, origin, leaf_name))
            else:
                for img_p, origin in pool:
                    sampled_leaf_neg.append((img_p, origin, leaf_name))
                deficit_i = assign_cnt - len(pool)
                secondary_debt += deficit_i
                leaf_remaining_candidates[leaf_name] = []
                logger.info(f"叶子目录 [{leaf_name}] 负样本不足，计划分摊 {assign_cnt} 张，实际仅有 {len(pool)} 张。产生二次债务 {deficit_i} 张。")
                
        # 跨叶子节点均衡消化二次债务
        if secondary_debt > 0:
            all_remains = []
            for leaf_name, items in leaf_remaining_candidates.items():
                for img_p, origin in items:
                    all_remains.append((img_p, origin, leaf_name))
            random.shuffle(all_remains)
            take_cnt = min(secondary_debt, len(all_remains))
            sampled_leaf_neg.extend(all_remains[:take_cnt])
            logger.info(f"已通过其他富余的叶子目录负样本消化了 {take_cnt}/{secondary_debt} 张二次债务。")
            
        final_neg_sampled.extend(sampled_leaf_neg)
    else:
        logger.info(f"纯背景负样本底片已包含 {total_bg_collected} 张，已完全覆盖全局目标需求 {target_neg_count} 张，无需从叶子目录中采纳负样本。")

    # c. 终极有放回过采样兜底
    current_neg_cnt = len(final_neg_sampled)
    if current_neg_cnt < target_neg_count:
        deficit = target_neg_count - current_neg_cnt
        if current_neg_cnt > 0:
            logger.warning(
                f"已抽干全数据集内所有的背景与叶子负样本底片，仍存在 {deficit} 张负样本缺口。由于 neg_ratio={neg_ratio:.1%} "
                f"配比要求，系统现启动终极有放回过采样，将复制生成负样本过采样副本 {deficit} 个。"
            )
            extra_neg = [random.choice(final_neg_sampled) for _ in range(deficit)]
            final_neg_sampled.extend(extra_neg)
        else:
            logger.warning("数据集中完全未探测到任何可用的背景负样本图，负样本数量降为 0。")

    # 5. 8:2 数据集随机划分
    all_packages = []
    for s, origin, dup_idx in final_pos_sampled:
        all_packages.append((s, origin, dup_idx))
    for img_p, origin, belong in final_neg_sampled:
        all_packages.append(((img_p, belong), origin, "neg"))

    random.shuffle(all_packages)
    split_idx = int(len(all_packages) * 0.8)
    train_packages = all_packages[:split_idx]
    val_packages = all_packages[split_idx:]

    post_split_stats = {
        "train": {"pos": [], "neg": []},
        "val": {"pos": [], "neg": []}
    }
    raw_box_records = []

    # 6. 执行文件软链挂载及标签写入
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
                post_split_stats[split_name]["pos"].append(s)

                rel_parts = img_path.parent.relative_to(Path(data_dir if origin == "new" else old_data_dir).resolve()).parts
                dir_prefix = "_".join(rel_parts) + "_" if rel_parts else ""
                dup_suffix = f"_dup{dup_idx}" if dup_idx > 0 else ""
                unique_name = f"{origin}_{dir_prefix}{img_path.stem}{dup_suffix}"

                dest_img_path = img_out_dir / f"{unique_name}{img_path.suffix}"
                process_and_link_image(img_path, dest_img_path)

                dest_txt_path = lbl_out_dir / f"{unique_name}.txt"
                img_w, img_h = s["img_w"], s["img_h"]

                bboxes_to_write = []
                for box in s["bboxes"]:
                    cls_val, xmin, ymin, xmax, ymax = box
                    cls_name = get_real_name(cls_val, new_id_to_class if origin == "new" else old_id_to_class)
                    global_class_id = class_to_id.get(cls_name, 0)

                    xmin_c = max(0.0, min(float(xmin), float(img_w)))
                    ymin_c = max(0.0, min(float(ymin), float(img_h)))
                    xmax_c = max(0.0, min(float(xmax), float(img_w)))
                    ymax_c = max(0.0, min(float(ymax), float(img_h)))

                    bw = xmax_c - xmin_c
                    bh = ymax_c - ymin_c
                    if bw <= 0 or bh <= 0:
                        continue

                    # 统一将宽度等比例归一化至 640px，便于跨数据集进行尺寸特征比对
                    w_norm_val = (bw / img_w) * 640.0
                    raw_box_records.append({
                        "origin": origin,
                        "leaf_node": s.get("node_name", "."),
                        "species": cls_name,
                        "w_norm_640": w_norm_val
                    })

                    x_center = (xmin_c + bw / 2) / img_w
                    y_center = (ymin_c + bh / 2) / img_h
                    w_norm = bw / img_w
                    h_norm = bh / img_h
                    bboxes_to_write.append((global_class_id, x_center, y_center, w_norm, h_norm))

                with open(dest_txt_path, "w", encoding="utf-8") as f:
                    for item in bboxes_to_write:
                        f.write(f"{item[0]} {item[1]:.6f} {item[2]:.6f} {item[3]:.6f} {item[4]:.6f}\n")
            else:
                # 负样本 ((img_path, belong), origin, "neg")
                (img_path, belong) = pkg[0]
                post_split_stats[split_name]["neg"].append({
                    "img_path": img_path,
                    "belong_name": belong,
                    "origin": origin
                })

                rel_parts = img_path.parent.relative_to(Path(data_dir if origin == "new" else old_data_dir).resolve()).parts
                dir_prefix = "_".join(rel_parts) + "_" if rel_parts else ""
                unique_name = f"{origin}_{dir_prefix}{img_path.stem}"

                dest_img_path = img_out_dir / f"{unique_name}{img_path.suffix}"
                process_and_link_image(img_path, dest_img_path)

                dest_txt_path = lbl_out_dir / f"{unique_name}.txt"
                with open(dest_txt_path, "w", encoding="utf-8") as f:
                    pass

    # 7. 调用画像直方图渲染模块
    from .preprocess_train_report import generate_plots_and_report
    generate_plots_and_report(
        dest_path=dest_path,
        raw_box_records=raw_box_records,
        pre_scan_samples={
            "new": {"pos": new_pos, "neg": new_neg},
            "old": {"pos": old_pos, "neg": old_neg}
        },
        post_split_stats=post_split_stats,
        global_classes=global_classes
    )

    # 8. 写入并输出 data.yaml 文件
    data_yaml_content = {
        "path": str(dest_path),
        "train": "images/train",
        "val": "images/val",
        "names": id_to_class
    }
    
    data_yaml_path = dest_path / "data.yaml"
    with open(data_yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data_yaml_content, f, allow_unicode=True, default_flow_style=False)
        
    logger.info(f"数据集自适应加工完成，已生成描述文件: {data_yaml_path}")
    return data_yaml_path
