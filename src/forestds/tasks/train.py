"""4estDS 模型训练任务模块。

基于极简原则，深度整合 Ultralytics 官方接口，主要实现：
1. VOC、COCO、YOLO 格式数据集的自适应规整、拆分与转换（使用软链接，零拷贝且不破坏用户原始数据）。
2. 自适应生成 YOLO 训练所需的 data.yaml 配置文件。
3. 调用 Ultralytics 训练接口，并将训练产物原生落盘至系统统一的 run 目录中。
"""
from __future__ import annotations

import json
import os
import random
import shutil
import xml.etree.ElementTree as ET
import yaml
from pathlib import Path
from typing import Any, Dict, List, Tuple
from loguru import logger
from PIL import Image

from ultralytics import YOLO
from ultralytics.data.converter import convert_coco
from forestds import paths
from forestds.db import writer
from forestds.utils.annotations import parse_voc_file
from ultralytics.utils.ops import xyxy2xywhn

# 启用 faulthandler 以在 segfault 时输出 Python traceback
import faulthandler as _faulthandler
_faulthandler.enable()


def patch_torch_save():
    import torch
    import torch.serialization
    import pickle

    try:
        original_save = torch.serialization._save

        def patched_save(obj, zip_file, pickle_module, pickle_protocol, _disable_byteorder_record):
            class WrappedPickleModule:
                def __init__(self, orig):
                    self.orig = orig

                def __getattr__(self, name):
                    if name == 'Pickler':
                        OrigPickler = getattr(self.orig, 'Pickler')

                        class InterceptingPickler(OrigPickler):
                            def __init_subclass__(cls, **kwargs):
                                super().__init_subclass__(**kwargs)
                                if 'persistent_id' in cls.__dict__:
                                    original_pid = cls.persistent_id

                                    def safe_persistent_id(*args, **kwargs):
                                        if len(args) >= 2:
                                            self_inst = args[0]
                                            obj = args[1]
                                        elif len(args) == 1:
                                            # 如果只有一个参数，根据它是否是 Pickler 实例来区分是 (self,) 还是 (obj,)
                                            if isinstance(args[0], OrigPickler):
                                                self_inst = args[0]
                                                obj = None
                                            else:
                                                self_inst = None
                                                obj = args[0]
                                        else:
                                            self_inst = None
                                            obj = None
                                        return original_pid(self_inst, obj)

                                    cls.persistent_id = safe_persistent_id

                        return InterceptingPickler
                    return getattr(self.orig, name)

            wrapped_pickle = WrappedPickleModule(pickle_module)
            return original_save(obj, zip_file, wrapped_pickle, pickle_protocol, _disable_byteorder_record)

        torch.serialization._save = patched_save
        logger.info("已成功应用动态 CPython 3.12 序列化兼容性补丁。")
    except Exception as e:
        logger.warning(f"应用序列化兼容性补丁失败: {e}")

# 支持的图片格式后缀
SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}


def safe_link(src: Path, dst: Path) -> None:
    """安全地创建软链接，若失败则降级为文件拷贝（确保跨文件系统或特殊环境下的兼容性）。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        os.symlink(src, dst)
    except Exception as e:
        logger.debug(f"软链接失败，降级为文件拷贝: {src} -> {dst}. 原因: {e}")
        shutil.copy2(src, dst)


def process_and_link_image(src: Path, dst: Path) -> None:
    """自适应处理图像通道并进行软链接挂载。
    
    若是标准 RGB (3通道) 图像，则直接进行软链接挂载（零拷贝）。
    若是 RGBA (4通道)、灰度图等非 3 通道图像，则自动转换为 3 通道 RGB 格式写入目标目录，
    从源头上防止 YOLO 训练时 Mosaic 等数据增强由于通道不匹配报 ValueError: could not broadcast 错误。
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
        
    try:
        with Image.open(src) as img:
            # 遥感影像常见 RGBA，或者是多通道，如果是标准的 3通道 RGB，直接创建软链接即可
            if img.mode == "RGB":
                os.symlink(src, dst)
            else:
                logger.debug(f"图像 {src.name} 模式为 {img.mode}，自动转换为 3通道 RGB 格式保存...")
                rgb_img = img.convert("RGB")
                rgb_img.save(dst)
    except Exception as e:
        logger.warning(f"自适应处理图像 {src.name} 通道失败: {e}，降级为直接拷贝。")
        try:
            shutil.copy2(src, dst)
        except Exception:
            pass





def find_image_for_xml(xml_path: Path, search_dirs: List[Path]) -> Path | None:
    """在指定的多个目录中寻找与 XML 同名的图像文件。"""
    stem = xml_path.stem
    for d in search_dirs:
        if not d.exists():
            continue
        for ext in SUPPORTED_IMAGE_EXTS:
            img_path = d / f"{stem}{ext}"
            if img_path.exists():
                return img_path
            # 兼容大小写后缀
            img_path_upper = d / f"{stem}{ext.upper()}"
            if img_path_upper.exists():
                return img_path_upper
    return None


def convert_voc_dataset(
    data_dir: Path, 
    dest_dir: Path, 
    split_ratio: float = 0.8
) -> Dict[int, str]:
    """转换 VOC 格式数据集到 YOLO 格式（含 8:2 自动拆分与软链接生成）。"""
    logger.info("检测到 VOC 格式数据集，开始解析与自适应转换...")
    
    # 兼容子目录结构
    anno_dir = data_dir / "Annotations"
    img_dirs = [data_dir / "JPEGImages", data_dir]
    
    if not anno_dir.exists():
        # 如果没有标准 Annotations，在 data_dir 下搜索所有 xml
        logger.warning(f"未找到标准 Annotations 目录，将在整个 {data_dir} 下递归寻找 XML 文件。")
        xml_files = list(data_dir.rglob("*.xml"))
        # 搜索图片的目录也包含所有递归子目录
        img_dirs.extend([p for p in data_dir.iterdir() if p.is_dir()])
    else:
        xml_files = list(anno_dir.glob("*.xml"))

    if not xml_files:
        raise FileNotFoundError(f"在 {data_dir} 下未找到任何 VOC XML 标注文件。")

    logger.info(f"共发现 {len(xml_files)} 个 XML 标注文件。")

    # 随机打乱用于划分 train/val
    random.seed(42)
    random.shuffle(xml_files)
    split_idx = int(len(xml_files) * split_ratio)
    train_xmls = xml_files[:split_idx]
    val_xmls = xml_files[split_idx:]

    # 收集类别
    classes_set = set()
    valid_samples = []  # List of (xml_path, img_path)

    for xml_path in xml_files:
        img_path = find_image_for_xml(xml_path, img_dirs)
        if not img_path:
            logger.debug(f"未找到与 XML 对应的图像文件，跳过: {xml_path.name}")
            continue
        valid_samples.append((xml_path, img_path))
        
        # 预先扫描以确定所有的 class names
        try:
            _, _, objects = parse_voc_file(xml_path)
            for obj in objects:
                classes_set.add(obj[0])
        except Exception as e:
            logger.warning(f"解析 XML 失败 {xml_path}: {e}")

    classes = sorted(list(classes_set))
    class_to_id = {name: idx for idx, name in enumerate(classes)}
    id_to_class = {idx: name for idx, name in enumerate(classes)}
    
    logger.info(f"自适应提取到的类别列表: {classes}")

    # 开始建立划分链接与 txt 文件写入
    for split_name, xml_list in [("train", train_xmls), ("val", val_xmls)]:
        img_out = dest_dir / "images" / split_name
        lbl_out = dest_dir / "labels" / split_name
        img_out.mkdir(parents=True, exist_ok=True)
        lbl_out.mkdir(parents=True, exist_ok=True)

        for xml_path in xml_list:
            # 找到对应的图像
            img_path = find_image_for_xml(xml_path, img_dirs)
            if not img_path:
                continue

            # 建立图像软链接（带通道规范化自适应）
            process_and_link_image(img_path, img_out / img_path.name)

            # 解析 XML 并写入 YOLO 格式的 txt
            try:
                import numpy as np
                width, height, objects = parse_voc_file(xml_path)
                # 如果 XML 中长宽缺失，从图像中读取
                if width <= 0 or height <= 0:
                    from PIL import Image
                    with Image.open(img_path) as pil_img:
                        width, height = pil_img.size

                txt_path = lbl_out / f"{xml_path.stem}.txt"
                
                # 过滤出有效的 bounding boxes
                valid_objects = []
                for class_name, xmin, ymin, xmax, ymax in objects:
                    if class_name in class_to_id:
                        valid_objects.append((class_to_id[class_name], xmin, ymin, xmax, ymax))
                
                with open(txt_path, "w", encoding="utf-8") as f:
                    if valid_objects:
                        xyxy = np.array([[obj[1], obj[2], obj[3], obj[4]] for obj in valid_objects], dtype=np.float64)
                        # 使用 xyxy2xywhn 矢量化转换并裁剪防溢出
                        xywhn = xyxy2xywhn(xyxy, w=width, h=height, clip=True)
                        for (class_id, _, _, _, _), box in zip(valid_objects, xywhn):
                            f.write(f"{class_id} {box[0]:.6f} {box[1]:.6f} {box[2]:.6f} {box[3]:.6f}\n")
            except Exception as e:
                logger.error(f"处理 VOC 数据样本失败 {xml_path.name}: {e}")

    return id_to_class


def convert_coco_dataset(
    data_dir: Path, 
    dest_dir: Path, 
    split_ratio: float = 0.8
) -> Dict[int, str]:
    """转换 COCO 格式数据集到 YOLO 格式。
    
    使用 Ultralytics 的 convert_coco，并对产生的 label 文件与图像软链接重新进行规整。
    """
    logger.info("检测到 COCO 格式数据集，开始解析与转换...")
    
    # 查找 coco annotations json
    anno_dir = data_dir / "annotations"
    if not anno_dir.exists():
        anno_dir = data_dir
        
    json_files = list(anno_dir.glob("*.json"))
    if not json_files:
        raise FileNotFoundError(f"在 {data_dir} 下未找到任何 COCO 格式的 JSON 标注文件。")
        
    # 创建临时转换输出目录
    tmp_converted = dest_dir / "tmp_coco_converted"
    tmp_converted.mkdir(parents=True, exist_ok=True)
    
    # 调用 ultralytics 转换接口
    convert_coco(labels_dir=str(anno_dir), save_dir=str(tmp_converted), use_segments=False, cls91to80=False)
    
    # 解析 json 提取 class 信息和建立图片软链接
    id_to_class: Dict[int, str] = {}
    
    # 我们遍历所有 json 读取类别映射关系，并找出图片路径
    img_search_dirs = [data_dir / "images", data_dir]
    # 如果有 train2017 等，也加进去
    img_search_dirs.extend([p for p in data_dir.iterdir() if p.is_dir()])
    
    all_img_filenames = {}
    for json_file in json_files:
        try:
            with open(json_file, encoding="utf-8") as f:
                coco_data = json.load(f)
            if "categories" in coco_data:
                for cat in coco_data["categories"]:
                    # COCO-to-YOLO class ID index typically maps from 0 onwards
                    # convert_coco uses `ann['category_id'] - 1` when cls91to80=False
                    cat_id = cat["id"] - 1
                    id_to_class[cat_id] = cat["name"]
            if "images" in coco_data:
                for img in coco_data["images"]:
                    all_img_filenames[Path(img["file_name"]).stem] = img["file_name"]
        except Exception as e:
            logger.warning(f"读取 COCO json 失败 {json_file}: {e}")

    # 将生成的 label 划分并连接到正式输出目录
    converted_labels_dir = tmp_converted / "labels"
    # 获取所有的 label txt 文件
    all_txt_files = list(converted_labels_dir.rglob("*.txt"))
    
    if not all_txt_files:
        raise FileNotFoundError("COCO 转换未生成任何 .txt 标签文件。")
        
    # 随机划分
    random.seed(42)
    random.shuffle(all_txt_files)
    split_idx = int(len(all_txt_files) * split_ratio)
    train_txts = all_txt_files[:split_idx]
    val_txts = all_txt_files[split_idx:]
    
    for split_name, txt_list in [("train", train_txts), ("val", val_txts)]:
        img_out = dest_dir / "images" / split_name
        lbl_out = dest_dir / "labels" / split_name
        img_out.mkdir(parents=True, exist_ok=True)
        lbl_out.mkdir(parents=True, exist_ok=True)
        
        for txt_path in txt_list:
            # 建立 label 链接
            safe_link(txt_path, lbl_out / txt_path.name)
            
            # 寻找对应的图片
            stem = txt_path.stem
            orig_filename = all_img_filenames.get(stem, f"{stem}.jpg")
            
            # 搜索原图
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
                # 模糊搜索同名不同后缀
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
                process_and_link_image(found_img, img_out / found_img.name)
            else:
                logger.warning(f"未能为标签 {txt_path.name} 找到对应的原始图像文件。")

    # 清理临时转换目录
    try:
        shutil.rmtree(tmp_converted)
    except Exception as e:
        logger.debug(f"清理临时转换目录失败: {e}")

    # 如果类别未定义，做兜底
    if not id_to_class:
        id_to_class = {0: "tree"}
        
    return id_to_class


def convert_yolo_dataset(
    data_dir: Path, 
    dest_dir: Path, 
    split_ratio: float = 0.8
) -> Dict[int, str]:
    """对 YOLO 格式数据集进行结构自适应规整或划分。"""
    logger.info("校验 YOLO 格式数据集...")
    
    # 情况 A: 已经包含了标准的 images/train 结构
    if (data_dir / "images" / "train").exists() and (data_dir / "labels" / "train").exists():
        logger.info("数据集已经符合标准 YOLO train/val 结构，建立目录级软链接...")
        for sub in ["images/train", "images/val", "labels/train", "labels/val"]:
            src_sub = data_dir / sub
            dst_sub = dest_dir / sub
            if src_sub.exists():
                safe_link(src_sub, dst_sub)
                
        # 尝试寻找并读取 names
        id_to_class = {}
        # 寻找已有的 data.yaml
        yaml_files = list(data_dir.glob("*.yaml")) + list(data_dir.glob("*.yml"))
        for yf in yaml_files:
            try:
                with open(yf, encoding="utf-8") as f:
                    yml_data = yaml.safe_load(f)
                if isinstance(yml_data, dict) and "names" in yml_data:
                    names_val = yml_data["names"]
                    if isinstance(names_val, list):
                        id_to_class = {i: n for i, n in enumerate(names_val)}
                    elif isinstance(names_val, dict):
                        id_to_class = {int(k): v for k, v in names_val.items()}
                    logger.info(f"从已有的 YAML 配置中读取到类别: {id_to_class}")
                    break
            except Exception as e:
                logger.debug(f"尝试读取现有 YAML 失败 {yf}: {e}")
                
        # 尝试 classes.txt
        if not id_to_class and (data_dir / "classes.txt").exists():
            try:
                with open(data_dir / "classes.txt", encoding="utf-8") as f:
                    lines = [line.strip() for line in f if line.strip()]
                id_to_class = {i: n for i, n in enumerate(lines)}
                logger.info(f"从 classes.txt 中读取到类别: {id_to_class}")
            except Exception as e:
                logger.debug(f"尝试读取 classes.txt 失败: {e}")
                
        if not id_to_class:
            id_to_class = {0: "tree"}  # 兜底
            
        return id_to_class

    # 情况 B: 扁平目录结构，含有图像和相应的 txt 文件，尚未做训练/测试集划分
    logger.info("检测到未划分的扁平 YOLO 目录，开始进行 8:2 随机划分...")
    
    # 动态定位图像源与标签源目录
    img_src_dir = data_dir / "images" if (data_dir / "images").is_dir() else data_dir
    lbl_src_dir = data_dir / "labels" if (data_dir / "labels").is_dir() else data_dir
    logger.info(f"自适应定位图像源目录: {img_src_dir}, 标签源目录: {lbl_src_dir}")
    
    # 检索所有图片
    all_images = []
    for ext in SUPPORTED_IMAGE_EXTS:
        all_images.extend(list(img_src_dir.glob(f"*{ext}")))
        all_images.extend(list(img_src_dir.glob(f"*{ext.upper()}")))

    # 过滤出有对应 txt 的图片
    valid_samples = []
    for img_path in all_images:
        txt_path = lbl_src_dir / f"{img_path.stem}.txt"
        if txt_path.exists():
            valid_samples.append((img_path, txt_path))
            
    if not valid_samples:
        raise FileNotFoundError(f"在 {data_dir} 下未找到任何配对的 YOLO 格式图片与 .txt 标签文件。")

    logger.info(f"找到配对的训练数据样本共 {len(valid_samples)} 个")

    # 划分
    random.seed(42)
    random.shuffle(valid_samples)
    split_idx = int(len(valid_samples) * split_ratio)
    train_samples = valid_samples[:split_idx]
    val_samples = valid_samples[split_idx:]

    from ..utils.progress import track_progress
    for split_name, samples in [("train", train_samples), ("val", val_samples)]:
        img_out = dest_dir / "images" / split_name
        lbl_out = dest_dir / "labels" / split_name
        img_out.mkdir(parents=True, exist_ok=True)
        lbl_out.mkdir(parents=True, exist_ok=True)

        for img_path, txt_path in track_progress(samples, desc=f"构建 {split_name} 数据集链接"):
            process_and_link_image(img_path, img_out / img_path.name)
            safe_link(txt_path, lbl_out / txt_path.name)

    # 尝试读取类别
    id_to_class = {}
    if (data_dir / "classes.txt").exists():
        try:
            with open(data_dir / "classes.txt", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
            id_to_class = {i: n for i, n in enumerate(lines)}
            logger.info(f"从 classes.txt 中提取到类别: {id_to_class}")
        except Exception as e:
            logger.debug(f"解析 classes.txt 失败: {e}")

    # 检查 data.yaml 
    yaml_files = list(data_dir.glob("*.yaml")) + list(data_dir.glob("*.yml"))
    for yf in yaml_files:
        try:
            with open(yf, encoding="utf-8") as f:
                yml_data = yaml.safe_load(f)
            if isinstance(yml_data, dict) and "names" in yml_data:
                names_val = yml_data["names"]
                if isinstance(names_val, list):
                    id_to_class = {i: n for i, n in enumerate(names_val)}
                elif isinstance(names_val, dict):
                    id_to_class = {int(k): v for k, v in names_val.items()}
                logger.info(f"从原有 YAML 中提取到类别: {id_to_class}")
                break
        except Exception as e:
            logger.debug(f"尝试读取 YAML 失败 {yf}: {e}")

    if not id_to_class:
        # 如果读取失败，扫描所有 txt 查找最大类别 index，防报错
        max_idx = 0
        for _, txt_path in valid_samples:
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
        # 若是 1 个，默认写 tree
        if len(id_to_class) == 1:
            id_to_class = {0: "tree"}
        logger.info(f"自动分析最大类别数，生成映射: {id_to_class}")

    return id_to_class


def ensure_data_yaml(
    data_dir_str: str, 
    dataset_format: str, 
    run_dir: Path,
    dest_subdir: str = "dataset"
) -> Path:
    """数据集校验与自适应结构规整，并动态生成对应的 data.yaml。
    
    返回:
        生成的 data.yaml 的绝对路径。
    """
    data_dir = Path(data_dir_str).resolve()
    if not data_dir.exists():
        raise FileNotFoundError(f"数据集目录不存在: {data_dir}")

    # 规范化目标目录
    dest_dir = run_dir / dest_subdir
    dest_dir.mkdir(parents=True, exist_ok=True)

    format_upper = dataset_format.upper()
    if format_upper == "VOC":
        id_to_class = convert_voc_dataset(data_dir, dest_dir)
    elif format_upper == "COCO":
        id_to_class = convert_coco_dataset(data_dir, dest_dir)
    elif format_upper == "YOLO":
        id_to_class = convert_yolo_dataset(data_dir, dest_dir)
    else:
        raise ValueError(f"不支持的数据集格式: {dataset_format}。可选: YOLO, VOC, COCO")

    # 构建并写入 data.yaml 文件
    data_yaml_content = {
        "path": str(dest_dir),
        "train": "images/train",
        "val": "images/val",
        "names": id_to_class
    }
    
    data_yaml_path = dest_dir / "data.yaml"
    with open(data_yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data_yaml_content, f, allow_unicode=True, default_flow_style=False)
        
    logger.info(f"数据集校验与规整成功，已自动生成训练描述文件: {data_yaml_path}")
    logger.debug(f"data.yaml 结构: {data_yaml_content}")
    
    return data_yaml_path


def run_train(
    data_dir: str,
    model_path: str,
    cfg_path: str,
    dataset_format: str = "YOLO",
    run_id: str | None = None,
    incremental: bool = False,
    base_dataset: str | None = None,
    base_format: str = "YOLO",
    freeze_layers: int = 10,
    epochs: int | None = None,
    task_type: str = "train",
) -> Dict[str, Any]:
    """4estDS 模型训练入口。
    
    解析和规整数据集，装载配置文件参数，直接调用官方 Ultralytics YOLO 进行训练。
    """
    # 动态应用 CPython 3.12 序列化补丁以支持 YOLO 模型保存
    patch_torch_save()

    # 强制打通并重置 ultralytics 日志通道，使之能向上传播并写入项目日志文件
    import logging
    ultra_log = logging.getLogger("ultralytics")
    ultra_log.propagate = True
    ultra_log.handlers = []

    logger.info("=" * 60)
    logger.info("4estDS 模型训练启动中...")
    logger.info(f"输入数据集: {data_dir} (格式: {dataset_format})")
    logger.info(f"基底模型: {model_path}")
    logger.info(f"参数配置: {cfg_path}")
    if incremental:
        logger.info(f"运行模式: 增量微调 (freeze_layers={freeze_layers}, base_dataset={base_dataset})")
    logger.info("=" * 60)

    # 1. 验证配置文件
    actual_cfg_path = Path(cfg_path).resolve()
    if not actual_cfg_path.exists():
        # 如果传入的不是绝对路径，尝试从项目根目录 configs/ 下查找
        fallback_path = Path(__file__).resolve().parent.parent.parent.parent / "configs" / cfg_path
        if fallback_path.exists():
            actual_cfg_path = fallback_path
        else:
            raise FileNotFoundError(f"配置文件未找到: {cfg_path}")

    # 读取配置文件以获取用户覆盖的训练参数
    with open(actual_cfg_path, "r", encoding="utf-8") as f:
        train_config = yaml.safe_load(f) or {}

    # 获取当前运行目录
    current_run_dir = paths.run_dir()
    current_run_dir.mkdir(parents=True, exist_ok=True)

    # 2. 规整并校验数据集，生成对应的 data.yaml
    if incremental and base_dataset:
        logger.info("开始混合新标注数据与基底主数据集，构建防灾难性遗忘的混合数据集...")
        
        # 规整新数据集到 new_structured 目录
        new_structured_dir = current_run_dir / "new_structured"
        ensure_data_yaml(data_dir, dataset_format, current_run_dir, dest_subdir="new_structured")
        
        # 规整基底数据集到 base_structured 目录
        base_structured_dir = current_run_dir / "base_structured"
        try:
            ensure_data_yaml(base_dataset, base_format, current_run_dir, dest_subdir="base_structured")
            base_ok = True
        except Exception as e:
            logger.warning(f"规整基底数据集失败 ({e})，将无法进行数据回放，仅使用新标数据集。")
            base_ok = False

        # 统计并打印新数据集与基底数据集的信息
        new_counts = {}
        for split in ["train", "val"]:
            new_img_dir = new_structured_dir / "images" / split
            new_lbl_dir = new_structured_dir / "labels" / split
            img_count = len(list(new_img_dir.glob("*"))) if new_img_dir.exists() else 0
            lbl_count = len(list(new_lbl_dir.glob("*"))) if new_lbl_dir.exists() else 0
            new_counts[split] = (img_count, lbl_count)
            
        logger.info(f"👉 新标注微调数据集统计：")
        logger.info(f"   - 训练集 (train): {new_counts['train'][0]} 对有效的图像-标注对")
        logger.info(f"   - 验证集 (val): {new_counts['val'][0]} 对有效的图像-标注对")

        base_counts = {}
        if base_ok:
            for split in ["train", "val"]:
                base_img_dir = base_structured_dir / "images" / split
                base_lbl_dir = base_structured_dir / "labels" / split
                img_count = len(list(base_img_dir.glob("*"))) if base_img_dir.exists() else 0
                lbl_count = len(list(base_lbl_dir.glob("*"))) if base_lbl_dir.exists() else 0
                base_counts[split] = (img_count, lbl_count)
            logger.info(f"👉 基底数据集统计：")
            logger.info(f"   - 训练集 (train): {base_counts['train'][0]} 张图像，{base_counts['train'][1]} 个有效标注")
            logger.info(f"   - 验证集 (val): {base_counts['val'][0]} 张图像，{base_counts['val'][1]} 个有效标注")

        # 创建混合数据集的终极目录
        final_dest_dir = current_run_dir / "dataset"
        final_dest_dir.mkdir(parents=True, exist_ok=True)

        new_names = {0: "tree"}
        new_yaml_path = new_structured_dir / "data.yaml"
        if new_yaml_path.exists():
            try:
                with open(new_yaml_path, "r", encoding="utf-8") as f:
                    new_yaml_data = yaml.safe_load(f) or {}
                    new_names = new_yaml_data.get("names", {0: "tree"})
            except Exception:
                pass

        # 遍历划分集 images/labels 并混合链接
        for split in ["train", "val"]:
            final_img_dir = final_dest_dir / "images" / split
            final_lbl_dir = final_dest_dir / "labels" / split
            final_img_dir.mkdir(parents=True, exist_ok=True)
            final_lbl_dir.mkdir(parents=True, exist_ok=True)

            # 新数据集链接
            new_img_src = new_structured_dir / "images" / split
            new_lbl_src = new_structured_dir / "labels" / split
            new_imgs = []
            if new_img_src.exists():
                new_imgs = [p for p in new_img_src.iterdir() if p.is_file() or p.is_symlink()]
                for img_p in new_imgs:
                    safe_link(img_p, final_img_dir / img_p.name)
            if new_lbl_src.exists():
                for lbl_p in new_lbl_src.iterdir():
                    if lbl_p.is_file() or lbl_p.is_symlink():
                        safe_link(lbl_p, final_lbl_dir / lbl_p.name)

            # 基底数据集抽样并链接（数据回放）
            if base_ok:
                base_img_src = base_structured_dir / "images" / split
                base_lbl_src = base_structured_dir / "labels" / split
                
                if base_img_src.exists():
                    base_imgs = [p for p in base_img_src.iterdir() if p.is_file() or p.is_symlink()]
                    if base_imgs and new_imgs:
                        # 抽样新图数量的 3 倍
                        sample_count = min(len(base_imgs), int(len(new_imgs) * 3))
                        # 强行设置最低阈值
                        min_samples = 30 if split == "train" else 10
                        sample_count = max(sample_count, min(len(base_imgs), min_samples))
                        
                        sampled_imgs = random.sample(base_imgs, sample_count)
                        logger.info(
                            f"在 {split} 集中：新图共 {len(new_imgs)} 张，"
                            f"计划从基底集中按 3.0 倍率（最低限制 {min_samples} 张）"
                            f"随机抽取 {sample_count} 张基底旧图像进行数据回放融合（基底总数: {len(base_imgs)} 张）。"
                        )
                        
                        for img_p in sampled_imgs:
                            safe_link(img_p, final_img_dir / img_p.name)
                            lbl_p = base_lbl_src / f"{img_p.stem}.txt"
                            if lbl_p.exists():
                                safe_link(lbl_p, final_lbl_dir / lbl_p.name)

        # 写入最终的 data.yaml
        data_yaml_content = {
            "path": str(final_dest_dir),
            "train": "images/train",
            "val": "images/val",
            "names": new_names
        }
        data_yaml_path = final_dest_dir / "data.yaml"
        with open(data_yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data_yaml_content, f, allow_unicode=True, default_flow_style=False)

        # 清理临时转换目录
        for temp_dir in [new_structured_dir, base_structured_dir]:
            if temp_dir and temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    logger.debug(f"清理临时目录 {temp_dir} 失败: {e}")
    else:
        if incremental:
            logger.warning("开启了增量训练模式，但未指定基底数据集路径或其不存在。数据回放防遗忘机制失效！")
        data_yaml_path = ensure_data_yaml(data_dir, dataset_format, current_run_dir)

    # 3. 组装 Ultralytics YOLO 训练参数
    train_kwargs = train_config.copy()
    
    # 强制覆盖的关键路径参数，使用 4estDS 体系路径
    train_kwargs["data"] = str(data_yaml_path)
    train_kwargs["project"] = str(paths.outputs_dir())
    train_kwargs["name"] = current_run_dir.name
    train_kwargs["exist_ok"] = True  # 避免 YOLO 添加数字后缀

    if incremental:
        # 增量模式下的超参重写与层冻结
        train_kwargs["freeze"] = freeze_layers
        
        # 初始学习率下调为原预设的 0.5 倍 (除以 2)
        orig_lr0 = train_kwargs.get("lr0", 0.01)
        train_kwargs["lr0"] = orig_lr0 * 0.5
        
        # 极短 warmup
        train_kwargs["warmup_epochs"] = 1
        
        # epochs 默认 20 轮，除非用户在 CLI 显式传递或配置文件中另有指定
        if epochs is not None:
            train_kwargs["epochs"] = epochs
        elif "epochs" not in train_kwargs:
            train_kwargs["epochs"] = 20
            
        logger.info(f"增量微调超参应用：freeze={freeze_layers}, lr0={train_kwargs['lr0']:.6f}, warmup_epochs=1, epochs={train_kwargs['epochs']}")
    else:
        # 普通训练模式，如果传入 epochs 则覆盖
        if epochs is not None:
            train_kwargs["epochs"] = epochs

    # 4. 加载基底模型并启动训练
    logger.info("载入模型权重并启动 YOLO 训练流程...")
    
    try:
        model = YOLO(model_path)
        # 写入运行日志 - 开始训练
        db_url = load_db_url()
        writer.start_run_log(
            run_id=run_id,
            task_type=task_type,
            model_arch=model_path,
            input_path=data_dir,
            params={
                "dataset_format": dataset_format,
                "config_file": str(actual_cfg_path),
                **train_config
            },
            url=db_url
        )
        
        # 执行训练
        results = model.train(**train_kwargs)
        
        # 获取最终生成的模型路径
        best_pt_path = current_run_dir / "weights" / "best.pt"
        if not best_pt_path.exists():
            logger.warning("在预期位置未找到 weights/best.pt，将扫描输出目录。")
            all_pt_files = list(current_run_dir.rglob("*.pt"))
            if all_pt_files:
                best_pt_path = all_pt_files[0]
                logger.info(f"定位到训练模型: {best_pt_path}")
            else:
                best_pt_path = None
                
        # 5. 更新运行日志 - 训练成功
        writer.finish_run_log(
            run_id=run_id,
            status="completed",
            error=None,
            url=db_url
        )
        
        logger.info(f"🎉 训练任务圆满完成！")
        if best_pt_path:
            logger.info(f"最佳模型权重位置: {best_pt_path}")
            
        return {
            "status": "success",
            "run_dir": str(current_run_dir),
            "best_model_path": str(best_pt_path) if best_pt_path else None,
            "results": results
        }
        
    except Exception as e:
        logger.exception("模型训练发生致命错误！")
        db_url = load_db_url()
        writer.finish_run_log(
            run_id=run_id,
            status="failed",
            error=str(e),
            url=db_url
        )
        raise e


def load_db_url() -> str | None:
    """载入数据库链接配置的辅助函数。"""
    try:
        from forestds.config import load_settings
        settings = load_settings()
        return settings.get("url", None)
    except Exception:
        return None
