"""命令行 draw-bbox 辅助工具实现。

职责：
  - 自动匹配搜索 YOLO、VOC、GeoJSON 标注文件。
  - 读取各类标注（类别仅做数字标识）。
  - 执行静默推理（无终端输出、无日志落地、不写入 SQLite），输出 YOLO 格式预测文本。
  - 绘制自适应画框图（黄色标注框，红色推理框；标注在左上角，推理在右上角）。
  - 所有输出文件名均携带 `YYYYMMDD_HHMM_` 年月日_时分前缀。
  - 画框图进行自适应等比例缩放（最大边 4096px）以防 OOM。
"""
from __future__ import annotations

import contextlib
import datetime
import io
import json
import logging
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Tuple, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from loguru import logger as log

from ..geo import resolve_geo
from .annotations import parse_voc_file, parse_yolo_file, parse_geojson_file


@contextlib.contextmanager
def silence_inference_env():
    """阻断所有终端输出、loguru 和 logging 的上下文管理器。"""
    logging.disable(logging.CRITICAL)
    log.disable("forestds")
    
    f_stdout = io.StringIO()
    f_stderr = io.StringIO()
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = f_stdout
    sys.stderr = f_stderr
    try:
        yield
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        logging.disable(logging.NOTSET)
        log.enable("forestds")


def find_label_file(image_path: str) -> str:
    """给定图像路径，寻找同级目录下或同名 labels 目录下的同名标注文件。

    按照同级 -> 对应 labels/ 的顺序，以及 .txt -> .xml -> .geojson -> .json 的优先级搜索。
    如果没找到，则抛出 FileNotFoundError。
    """
    path = Path(image_path)
    stem = path.stem
    parent = path.parent

    # 构造待查目录列表
    search_dirs = [parent]
    
    # 如果当前路径在 images/ 目录下，寻找对应的 labels/ 目录
    # 比如: /path/to/images/train/1.jpg -> /path/to/labels/train/
    if "images" in parent.parts:
        parts = list(parent.parts)
        idx = parts.index("images")
        parts[idx] = "labels"
        label_dir = Path(*parts)
        search_dirs.append(label_dir)

    for d in search_dirs:
        if not d.exists():
            continue
        for ext in [".txt", ".xml", ".geojson", ".json"]:
            lbl_file = d / f"{stem}{ext}"
            if lbl_file.exists():
                return str(lbl_file)
            # 兼容大写后缀
            lbl_file_upper = d / f"{stem}{ext.upper()}"
            if lbl_file_upper.exists():
                return str(lbl_file_upper)

    raise FileNotFoundError(
        f"未能在同级目录或对应 labels/ 下找到与图像 {image_path} stem 为 '{stem}' 的匹配标注文件（支持 .txt, .xml, .geojson, .json）。"
    )


def load_annotations(lbl_path: str, img_w: int, img_h: int, image_path: str) -> List[Tuple[int, float, float, float, float]]:
    """解析 YOLO(.txt)、VOC(.xml)、GeoJSON(.geojson) 标注文件。
    
    返回:
        List of (class_id, x1, y1, x2, y2)
    """
    path = Path(lbl_path)
    suffix = path.suffix.lower()
    boxes: List[Tuple[int, float, float, float, float]] = []
    name_to_id = {}

    if suffix == ".txt":
        boxes = parse_yolo_file(path, img_w, img_h)
    elif suffix == ".xml":
        try:
            _, _, objects = parse_voc_file(path)
            for name, xmin, ymin, xmax, ymax in objects:
                cls_id = int(name) if name.isdigit() else name_to_id.setdefault(name, len(name_to_id))
                boxes.append((cls_id, xmin, ymin, xmax, ymax))
        except Exception as e:
            log.error("解析 VOC XML 标注失败 {}: {}", lbl_path, e)
    elif suffix in (".geojson", ".json"):
        try:
            transform = None
            try:
                geo = resolve_geo(image_path)
                transform = geo.transform
            except Exception:
                pass
            boxes = parse_geojson_file(path, transform=transform, name_to_id=name_to_id)
        except Exception as e:
            log.error("解析 GeoJSON 标注失败 {}: {}", lbl_path, e)
    else:
        raise ValueError(f"不支持的标注格式: {suffix}")

    return boxes


def run_silent_inference(image_path: str, settings) -> List[Tuple[int, float, float, float, float, float]]:
    """在隔离/静默环境中执行 YOLO 推理，并在坐标系还原后返回结果。"""
    # 1. 估算自适应缩放（防止推理阶段大图引发 OOM，默认在 2048px 以下进行单前向预测）
    img = Image.open(image_path).convert("RGB")
    orig_w, orig_h = img.size
    
    max_infer_sz = 2048
    if max(orig_w, orig_h) > max_infer_sz:
        scale = max_infer_sz / max(orig_w, orig_h)
        new_w = int(round(orig_w * scale))
        new_h = int(round(orig_h * scale))
        img_resized = img.resize((new_w, new_h), resample=Image.BILINEAR)
        pixels = np.array(img_resized)
        infer_w, infer_h = new_w, new_h
    else:
        scale = 1.0
        pixels = np.array(img)
        infer_w, infer_h = orig_w, orig_h

    # 2. 延迟加载并获取 detector
    from ..detect.registry import get_detector
    from ..detect.base import Window

    arch = settings.get("detect.arch", "ultralytics")
    weights = settings.get(f"detect.models.{arch}.weights", settings.get("detect.weights"))
    conf = float(settings.get("conf_threshold", 0.25))
    iou = float(settings.get("detect.iou_threshold", 0.55))
    imgsz = int(settings.get("detect.model_input", settings.get("model_input", 1024)))
    log.info("正在静默推理 (模型: {}, 输入尺寸: {}x{})...", weights, infer_w, infer_h)

    with silence_inference_env():
        detector = get_detector(
            arch,
            weights=weights,
            conf=conf,
            iou=iou,
            imgsz=imgsz,
        )
        detector.ensure_loaded()
        win = Window(x=0, y=0, w=infer_w, h=infer_h, pixels=pixels)
        detections = detector.predict(win)


    # 3. 映射回原图坐标
    results: List[Tuple[int, float, float, float, float, float]] = []
    for det in detections:
        x1 = det.x1 / scale
        y1 = det.y1 / scale
        x2 = det.x2 / scale
        y2 = det.y2 / scale
        
        # 只保留数字标识
        try:
            cls_id = int(det.label)
        except ValueError:
            cls_id = 0
            
        results.append((cls_id, x1, y1, x2, y2, det.score))

    return results


def draw_bbox_main(
    image_path: str,
    label_path: Optional[str] = None,
    with_infer: bool = False,
    settings: Optional[dict] = None,
) -> int:
    """draw-bbox 命令主要逻辑实现。"""
    from .. import paths
    paths.ensure_home()
    
    img_path = Path(image_path)
    if not img_path.exists():
        log.error("找不到输入影像: {}", image_path)
        return 1

    # 1. 自动匹配标注文件
    resolved_label_path = label_path
    if not resolved_label_path:
        try:
            resolved_label_path = find_label_file(image_path)
        except FileNotFoundError as e:
            if not with_infer:
                log.error("{}", e)
                return 1
            # 如果是 with-infer 模式，标注文件非强必需
            log.warning("未匹配到标注文件，仅绘制推理框。")
            resolved_label_path = None

    # 2. 读取图像尺寸以防画图 OOM，若大边 > 4096，等比例缩放至最大边 4096px
    orig_img = Image.open(img_path).convert("RGB")
    orig_w, orig_h = orig_img.size
    
    max_draw_sz = 4096
    if max(orig_w, orig_h) > max_draw_sz:
        draw_scale = max_draw_sz / max(orig_w, orig_h)
        draw_w = int(round(orig_w * draw_scale))
        draw_h = int(round(orig_h * draw_scale))
        draw_img = orig_img.resize((draw_w, draw_h), resample=Image.BILINEAR)
        log.info("影像像素过大 ({}x{})，等比例缩放至最大边 {}px 以防画图 OOM。", orig_w, orig_h, max_draw_sz)
    else:
        draw_scale = 1.0
        draw_w, draw_h = orig_w, orig_h
        draw_img = orig_img.copy()

    # 生成 YYYYMMDD_HHMM 前缀
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    cache_dir = paths.subdir("tmp") / "draw_boxes"
    cache_dir.mkdir(parents=True, exist_ok=True)


    # 3. 加载并缩放标注框
    label_boxes: List[Tuple[int, float, float, float, float]] = []
    if resolved_label_path:
        raw_labels = load_annotations(resolved_label_path, orig_w, orig_h, image_path)
        # 将原始标注坐标缩放到画图图像的分辨率
        for cls_id, x1, y1, x2, y2 in raw_labels:
            label_boxes.append((
                cls_id,
                x1 * draw_scale,
                y1 * draw_scale,
                x2 * draw_scale,
                y2 * draw_scale
            ))

    # 4. 执行推理并还原缩放
    infer_boxes: List[Tuple[int, float, float, float, float, float]] = []
    if with_infer:
        if settings is None:
            from ..config import load_settings
            settings = load_settings()
        
        # 获取推理出来的原图坐标框
        raw_infers = run_silent_inference(image_path, settings)
        
        # 缩放到画图图像分辨率 (不保存文本结果，画完即弃)
        for cls_id, x1, y1, x2, y2, conf in raw_infers:
            infer_boxes.append((
                cls_id,
                x1 * draw_scale,
                y1 * draw_scale,
                x2 * draw_scale,
                y2 * draw_scale,
                conf
            ))

    # 打印合并日志
    log.info("标注 {} 个 -> 推理 {} 个", len(label_boxes), len(infer_boxes))

    # 5. 画图
    draw = ImageDraw.Draw(draw_img)
    # 自适应字体大小与线宽
    lw = max(2, int(round(min(draw_w, draw_h) / 300.0)))
    font_size = max(12, int(round(min(draw_w, draw_h) / 60.0)))
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", size=font_size)
    except IOError:
        font = ImageFont.load_default()

    # 绘制黄色标注框 (左上角标签)
    for cls_id, x1, y1, x2, y2 in label_boxes:
        draw.rectangle([x1, y1, x2, y2], outline=(255, 255, 0), width=lw)
        tag = f"{cls_id}"
        # 画文字底色背景，增加对比度
        try:
            tw, th = font.getbbox(tag)[2:4]
        except AttributeError:
            tw, th = draw.textsize(tag, font=font) if hasattr(draw, "textsize") else (font_size * len(tag) * 0.6, font_size)
        
        draw.rectangle([x1, y1 - th, x1 + tw, y1], fill=(255, 255, 0))
        draw.text((x1, y1 - th), tag, fill=(0, 0, 0), font=font)

    # 绘制红色推理框 (右上角标签)
    for cls_id, x1, y1, x2, y2, conf in infer_boxes:
        draw.rectangle([x1, y1, x2, y2], outline=(255, 0, 0), width=lw)
        tag = f"{cls_id}, {conf:.2f}"
        try:
            tw, th = font.getbbox(tag)[2:4]
        except AttributeError:
            tw, th = draw.textsize(tag, font=font) if hasattr(draw, "textsize") else (font_size * len(tag) * 0.6, font_size)
            
        draw.rectangle([x2 - tw, y1 - th, x2, y1], fill=(255, 0, 0))
        draw.text((x2 - tw, y1 - th), tag, fill=(255, 255, 255), font=font)

    # 6. 保存图像
    img_out_path = cache_dir / f"{timestamp}_{img_path.stem}_drawn.jpg"
    draw_img.save(img_out_path, quality=95)
    log.info("绘制图像: {}", img_out_path)
    return 0
