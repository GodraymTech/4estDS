"""数据集高效预处理工具。

职责：
  - 自动检测并校验 YOLO/VOC/COCO 格式数据集。
  - 将数据集物理拷贝或格式转换到符合 Ultralytics YOLO 训练的规范化目录结构中（禁止软链接）。
  - 只要不是 RGB 格式的 JPG 影像，统统自动转换为 3通道 RGB JPEG 格式保存。
  - 并行高速执行，充分利用多核 CPU。
  - 动态生成训练所需的 data.yaml 描述文件。
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from PIL import Image
import yaml
from loguru import logger

# 复用项目现有的数据集辅助接口
from forestds.tasks.train import SUPPORTED_IMAGE_EXTS, find_image_for_xml


def _worker_process_task(task: dict) -> tuple[bool, str]:
    """并行工作进程中执行的单个子任务，返回 (是否成功, 状态信息/错误原因)"""
    task_type = task["type"]
    try:
        if task_type == "image":
            src = Path(task["src"])
            dst = Path(task["dst"])
            dst.parent.mkdir(parents=True, exist_ok=True)
            
            # 检查是否已经是 RGB JPG/JPEG
            is_rgb_jpg = False
            if src.suffix.lower() in (".jpg", ".jpeg"):
                try:
                    with Image.open(src) as img:
                        # 只有当 mode 为 RGB 并且编码格式为 JPEG 时才直接拷贝，以防伪造后缀的非 JPG
                        if img.mode == "RGB" and img.format == "JPEG":
                            is_rgb_jpg = True
                except Exception:
                    pass
            
            if is_rgb_jpg:
                shutil.copy2(src, dst)
                return True, "copied"
            else:
                with Image.open(src) as img:
                    rgb_img = img.convert("RGB")
                    # 统一保存为高质量 JPEG 格式
                    rgb_img.save(dst, "JPEG", quality=95)
                return True, "converted"
                
        elif task_type == "yolo_label":
            src = Path(task["src"])
            dst = Path(task["dst"])
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            return True, "label"
            
        elif task_type == "voc_label":
            src = Path(task["src"])
            dst = Path(task["dst"])
            class_to_id = task["class_to_id"]
            img_src = Path(task["img_src"])
            dst.parent.mkdir(parents=True, exist_ok=True)
            
            from forestds.utils.annotations import parse_voc_file
            from ultralytics.utils.ops import xyxy2xywhn
            import numpy as np
            
            width, height, objects = parse_voc_file(src)
            
            # 若 XML 中缺失尺寸信息，回退通过 PIL 读取原图
            if width <= 0 or height <= 0:
                with Image.open(img_src) as pil_img:
                    width, height = pil_img.size
            
            valid_objects = []
            for name, xmin, ymin, xmax, ymax in objects:
                if name in class_to_id:
                    valid_objects.append((class_to_id[name], xmin, ymin, xmax, ymax))
            
            with open(dst, "w", encoding="utf-8") as f:
                if valid_objects:
                    xyxy = np.array([[obj[1], obj[2], obj[3], obj[4]] for obj in valid_objects], dtype=np.float64)
                    # 批量转换为归一化 xywhn 并进行溢出截断
                    xywhn = xyxy2xywhn(xyxy, w=width, h=height, clip=True)
                    
                    for (class_id, _, _, _, _), box in zip(valid_objects, xywhn):
                        f.write(f"{class_id} {box[0]:.6f} {box[1]:.6f} {box[2]:.6f} {box[3]:.6f}\n")
            return True, "label"
            
        else:
            return False, f"未知的任务类型: {task_type}"
            
    except Exception as e:
        import traceback
        return False, f"处理文件 {task.get('src')} 时出错: {e}\n{traceback.format_exc()}"


def extract_yolo_classes(source_dir: Path, valid_pairs: list) -> dict[int, str]:
    """提取或猜测 YOLO 格式数据集中的类别映射表"""
    # 1. 优先尝试从 *.yaml/ *.yml 中寻找
    yaml_files = list(source_dir.glob("*.yaml")) + list(source_dir.glob("*.yml"))
    for yf in yaml_files:
        try:
            with open(yf, encoding="utf-8") as f:
                yml_data = yaml.safe_load(f)
            if isinstance(yml_data, dict) and "names" in yml_data:
                names_val = yml_data["names"]
                if isinstance(names_val, list):
                    return {i: n for i, n in enumerate(names_val)}
                elif isinstance(names_val, dict):
                    return {int(k): v for k, v in names_val.items()}
        except Exception:
            pass

    # 2. 尝试读取 classes.txt
    classes_txt = source_dir / "classes.txt"
    if not classes_txt.exists() and (source_dir / "labels").exists():
        classes_txt = source_dir / "labels" / "classes.txt"
    if classes_txt.exists():
        try:
            with open(classes_txt, encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
            return {i: n for i, n in enumerate(lines)}
        except Exception:
            pass

    # 3. 扫描标注文件分析最大类别索引
    max_idx = 0
    for _, txt_path in valid_pairs:
        try:
            with open(txt_path, "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split()
                    if parts:
                        cls_id = int(parts[0])
                        if cls_id > max_idx:
                            max_idx = cls_id
        except Exception:
            pass
    id_to_class = {i: f"class_{i}" for i in range(max_idx + 1)}
    if len(id_to_class) == 1:
        id_to_class = {0: "tree"}
    return id_to_class


def standardize_ds(
    source_dir: str | Path,
    dest_dir: str | Path | None = None,
    dataset_format: str = "auto",
    split_ratio: float = 0.8,
    num_workers: int | None = None
) -> None:
    """数据集物理规整与标准化主入口"""
    source_dir = Path(source_dir).resolve()
    if dest_dir is None:
        dest_dir = source_dir.parent / f"{source_dir.name}_standard"
    else:
        dest_dir = Path(dest_dir).resolve()
    
    if not source_dir.exists():
        raise FileNotFoundError(f"输入的数据集源目录不存在: {source_dir}")
        
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. 自动检测格式
    format_upper = dataset_format.upper()
    if format_upper == "AUTO":
        json_files = list(source_dir.glob("*.json"))
        if (source_dir / "annotations").exists():
            json_files += list((source_dir / "annotations").glob("*.json"))
            
        xml_files = list(source_dir.glob("*.xml"))
        if (source_dir / "Annotations").exists():
            xml_files += list((source_dir / "Annotations").glob("*.xml"))
            
        if json_files:
            format_upper = "COCO"
        elif xml_files:
            format_upper = "VOC"
        else:
            format_upper = "YOLO"
            
    logger.info(f"👉 数据集格式定位为: {format_upper}")
    
    # 2. 检查是否已经是符合 YOLO 标准拆分的多目录结构
    is_already_split = False
    if format_upper == "YOLO":
        if (source_dir / "images" / "train").exists() and (source_dir / "labels" / "train").exists():
            is_already_split = True
            logger.info("检测到输入目录已包含标准 train/val 子划分，将保持原有的划分结构。")
            
    # 3. 收集标注与图片配对，构建多进程子任务
    tasks = []
    id_to_class = {}
    tmp_coco_dir = None
    
    try:
        if is_already_split:
            # 已经划分的 YOLO 数据集
            for split in ["train", "val"]:
                img_src_dir = source_dir / "images" / split
                lbl_src_dir = source_dir / "labels" / split
                
                img_files = []
                for ext in SUPPORTED_IMAGE_EXTS:
                    img_files.extend(list(img_src_dir.glob(f"*{ext}")))
                    img_files.extend(list(img_src_dir.glob(f"*{ext.upper()}")))
                    
                valid_pairs = []
                for img_p in img_files:
                    txt_p = lbl_src_dir / f"{img_p.stem}.txt"
                    if txt_p.exists():
                        valid_pairs.append((img_p, txt_p))
                        
                for img_p, txt_p in valid_pairs:
                    tasks.append({
                        "type": "image",
                        "src": str(img_p),
                        "dst": str(dest_dir / "images" / split / f"{img_p.stem}.jpg")
                    })
                    tasks.append({
                        "type": "yolo_label",
                        "src": str(txt_p),
                        "dst": str(dest_dir / "labels" / split / f"{txt_p.stem}.txt")
                    })
            id_to_class = extract_yolo_classes(source_dir, [])
            
        elif format_upper == "YOLO":
            # 扁平结构 YOLO
            img_src_dir = source_dir / "images" if (source_dir / "images").is_dir() else source_dir
            lbl_src_dir = source_dir / "labels" if (source_dir / "labels").is_dir() else source_dir
            
            img_files = []
            for ext in SUPPORTED_IMAGE_EXTS:
                img_files.extend(list(img_src_dir.glob(f"*{ext}")))
                img_files.extend(list(img_src_dir.glob(f"*{ext.upper()}")))
                
            valid_pairs = []
            for img_p in img_files:
                txt_p = lbl_src_dir / f"{img_p.stem}.txt"
                if txt_p.exists():
                    valid_pairs.append((img_p, txt_p))
                    
            if not valid_pairs:
                raise FileNotFoundError(f"在 {source_dir} 下未找到任何配对的 YOLO 图像与 .txt 标签文件。")
                
            # 随机拆分
            random.seed(42)
            random.shuffle(valid_pairs)
            split_idx = int(len(valid_pairs) * split_ratio)
            train_pairs = valid_pairs[:split_idx]
            val_pairs = valid_pairs[split_idx:]
            
            for split, pairs in [("train", train_pairs), ("val", val_pairs)]:
                for img_p, txt_p in pairs:
                    tasks.append({
                        "type": "image",
                        "src": str(img_p),
                        "dst": str(dest_dir / "images" / split / f"{img_p.stem}.jpg")
                    })
                    tasks.append({
                        "type": "yolo_label",
                        "src": str(txt_p),
                        "dst": str(dest_dir / "labels" / split / f"{txt_p.stem}.txt")
                    })
            id_to_class = extract_yolo_classes(source_dir, valid_pairs)
            
        elif format_upper == "VOC":
            # VOC 格式
            anno_dir = source_dir / "Annotations"
            img_dirs = [source_dir / "JPEGImages", source_dir]
            if not anno_dir.exists():
                xml_files = list(source_dir.rglob("*.xml"))
                img_dirs.extend([p for p in source_dir.iterdir() if p.is_dir()])
            else:
                xml_files = list(anno_dir.glob("*.xml"))
                
            if not xml_files:
                raise FileNotFoundError(f"在 {source_dir} 下未找到任何 VOC XML 标注文件。")
                
            valid_pairs = []
            classes_set = set()
            for xml_p in xml_files:
                img_p = find_image_for_xml(xml_p, img_dirs)
                if not img_p:
                    continue
                valid_pairs.append((xml_p, img_p))
                
                # 快速解析 XML 收集类别名
                try:
                    from forestds.utils.annotations import parse_voc_file
                    _, _, objects = parse_voc_file(xml_p)
                    for name, _, _, _, _ in objects:
                        if name:
                            classes_set.add(name)
                except Exception:
                    pass
                    
            classes = sorted(list(classes_set))
            class_to_id = {name: idx for idx, name in enumerate(classes)}
            id_to_class = {idx: name for idx, name in enumerate(classes)}
            
            # 随机拆分
            random.seed(42)
            random.shuffle(valid_pairs)
            split_idx = int(len(valid_pairs) * split_ratio)
            train_pairs = valid_pairs[:split_idx]
            val_pairs = valid_pairs[split_idx:]
            
            for split, pairs in [("train", train_pairs), ("val", val_pairs)]:
                for xml_p, img_p in pairs:
                    tasks.append({
                        "type": "image",
                        "src": str(img_p),
                        "dst": str(dest_dir / "images" / split / f"{img_p.stem}.jpg")
                    })
                    tasks.append({
                        "type": "voc_label",
                        "src": str(xml_p),
                        "dst": str(dest_dir / "labels" / split / f"{xml_p.stem}.txt"),
                        "class_to_id": class_to_id,
                        "img_src": str(img_p)
                    })
                    
        elif format_upper == "COCO":
            # COCO 格式
            anno_dir = source_dir / "annotations"
            if not anno_dir.exists():
                anno_dir = source_dir
            json_files = list(anno_dir.glob("*.json"))
            if not json_files:
                raise FileNotFoundError(f"在 {source_dir} 下未找到任何 COCO 格式的 JSON 标注文件。")
                
            tmp_coco_dir = dest_dir / "tmp_coco_converted"
            tmp_coco_dir.mkdir(parents=True, exist_ok=True)
            
            # 调用官方转换工具输出 txt
            from ultralytics.data.converter import convert_coco
            logger.info("正在执行 COCO 标注格式转换...")
            convert_coco(labels_dir=str(anno_dir), save_dir=str(tmp_coco_dir), use_segments=False, cls91to80=False)
            
            # 读 COCO json 统计类别和寻找源图
            img_search_dirs = [source_dir / "images", source_dir]
            img_search_dirs.extend([p for p in source_dir.iterdir() if p.is_dir()])
            
            all_img_filenames = {}
            for jf in json_files:
                try:
                    with open(jf, encoding="utf-8") as f:
                        coco_data = json.load(f)
                    if "categories" in coco_data:
                        for cat in coco_data["categories"]:
                            cat_id = cat["id"] - 1
                            id_to_class[cat_id] = cat["name"]
                    if "images" in coco_data:
                        for img in coco_data["images"]:
                            all_img_filenames[Path(img["file_name"]).stem] = img["file_name"]
                except Exception:
                    pass
                    
            converted_labels_dir = tmp_coco_dir / "labels"
            all_txt_files = list(converted_labels_dir.rglob("*.txt"))
            if not all_txt_files:
                raise FileNotFoundError("COCO 转换未产生任何标签文件。")
                
            # 随机划分
            random.seed(42)
            random.shuffle(all_txt_files)
            split_idx = int(len(all_txt_files) * split_ratio)
            train_txts = all_txt_files[:split_idx]
            val_txts = all_txt_files[split_idx:]
            
            for split, txt_list in [("train", train_txts), ("val", val_txts)]:
                for txt_p in txt_list:
                    stem = txt_p.stem
                    orig_filename = all_img_filenames.get(stem, f"{stem}.jpg")
                    
                    found_img = None
                    for d in img_search_dirs:
                        potential = d / orig_filename
                        if potential.exists():
                            found_img = potential
                            break
                        potential_stem = d / f"{stem}{Path(orig_filename).suffix}"
                        if potential_stem.exists():
                            found_img = potential_stem
                            break
                    if not found_img:
                        # 模糊后缀搜索
                        for d in img_search_dirs:
                            if not d.exists():
                                continue
                            for ext in SUPPORTED_IMAGE_EXTS:
                                p = d / f"{stem}{ext}"
                                if p.exists():
                                    found_img = p
                                    break
                                p_upper = d / f"{stem}{ext.upper()}"
                                if p_upper.exists():
                                    found_img = p_upper
                                    break
                            if found_img:
                                break
                                
                    if found_img:
                        tasks.append({
                            "type": "image",
                            "src": str(found_img),
                            "dst": str(dest_dir / "images" / split / f"{found_img.stem}.jpg")
                        })
                        tasks.append({
                            "type": "yolo_label",
                            "src": str(txt_p),
                            "dst": str(dest_dir / "labels" / split / f"{txt_p.stem}.txt")
                        })
                        
        logger.info(f"📊 构建完成待执行子任务数: {len(tasks)}")
        
        # 4. 并行高效执行复制与色彩空间处理
        from forestds.utils.progress import track_progress
        
        # 统计结果指标
        copied_cnt = 0
        converted_cnt = 0
        label_cnt = 0
        error_cnt = 0
        
        # 多进程并行处理
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = {executor.submit(_worker_process_task, task): task for task in tasks}
            
            for future in track_progress(as_completed(futures), desc="并行整理数据集中", total=len(futures)):
                success, result_info = future.result()
                if success:
                    if result_info == "copied":
                        copied_cnt += 1
                    elif result_info == "converted":
                        converted_cnt += 1
                    elif result_info == "label":
                        label_cnt += 1
                else:
                    error_cnt += 1
                    logger.error(result_info)
                    
        logger.info(f"✅ 数据规整任务完成。")
        logger.info(f"   - 图像直接拷贝: {copied_cnt} 张")
        logger.info(f"   - 图像格式/RGB转换拷贝: {converted_cnt} 张")
        logger.info(f"   - 标注文件写入: {label_cnt} 个")
        if error_cnt > 0:
            logger.warning(f"   - 失败文件数: {error_cnt}，详细报错如上。")
            
        # 5. 生成 data.yaml
        data_yaml_content = {
            "path": str(dest_dir),
            "train": "images/train",
            "val": "images/val",
            "names": id_to_class
        }
        data_yaml_path = dest_dir / "data.yaml"
        with open(data_yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data_yaml_content, f, allow_unicode=True, default_flow_style=False)
        logger.info(f"已经自动在目标目录下输出 data.yaml: {data_yaml_path}")
        
    finally:
        # 清理临时转换目录
        if tmp_coco_dir and tmp_coco_dir.exists():
            try:
                shutil.rmtree(tmp_coco_dir)
            except Exception as e:
                logger.debug(f"清理临时 COCO 转换目录失败: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="非常高效地将输入的各种数据集目录改造成适合 Ultralytics YOLO 训练的物理新目录结构（非软链接 + 图像 RGB/JPG 化）。"
    )
    parser.add_argument("-s", "--source", required=True, help="输入的数据集源目录")
    parser.add_argument("-d", "--dest", required=True, help="规整规范化后的输出目标目录")
    parser.add_argument("-f", "--format", default="auto", choices=["auto", "YOLO", "VOC", "COCO"], help="数据集原始格式，默认为自动匹配")
    parser.add_argument("-r", "--split-ratio", type=float, default=0.8, help="无预先划分的数据集 train 占比，默认 0.8 (即 8:2)")
    parser.add_argument("-w", "--workers", type=int, default=None, help="并行工作进程数，默认自动匹配 CPU 核心数")
    
    args = parser.parse_args()
    
    try:
        standardize_ds(
            source_dir=args.source,
            dest_dir=args.dest,
            dataset_format=args.format,
            split_ratio=args.split_ratio,
            num_workers=args.workers
        )
    except Exception as e:
        logger.exception(f"执行失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
