"""标注数据解析与转换适配层。

职责：
  - 解析 YOLO、VOC XML 和 GeoJSON 等常见标注文件。
  - 基于 Ultralytics 底层的高性能 Op 算子（如 xyxy2xywhn 和 xywhn2xyxy）执行坐标转化与归一化。
  - 作为通用标注基础层，服务于数据集规整 (standardize_ds) 与画框调试 (draw-bbox)。
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
from loguru import logger

# 引入 Ultralytics 内置的高性能算子
from ultralytics.utils.ops import xyxy2xywhn, xywhn2xyxy

SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}


def find_image_for_xml(xml_path: Path, search_dirs: list[Path]) -> Path | None:
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


def parse_voc_file(xml_path: Path) -> tuple[int, int, list[tuple[str, float, float, float, float]]]:
    """解析 VOC 格式的 XML 标注文件。
    
    返回:
        width, height, list of (class_name, xmin, ymin, xmax, ymax) 在绝对像素系中。
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    size_node = root.find("size")
    if size_node is not None:
        width = int(size_node.findtext("width", "0"))
        height = int(size_node.findtext("height", "0"))
    else:
        width, height = 0, 0

    objects = []
    for obj in root.findall("object"):
        name = obj.findtext("name")
        bndbox = obj.find("bndbox")
        if not name or bndbox is None:
            continue
        try:
            xmin = float(bndbox.findtext("xmin"))
            ymin = float(bndbox.findtext("ymin"))
            xmax = float(bndbox.findtext("xmax"))
            ymax = float(bndbox.findtext("ymax"))
            objects.append((name, xmin, ymin, xmax, ymax))
        except Exception as e:
            logger.warning(f"解析 XML 中的边界框坐标失败: {e}")

    return width, height, objects


def parse_yolo_file(txt_path: Path, img_w: int, img_h: int) -> list[tuple[int, float, float, float, float]]:
    """解析 YOLO 格式的 TXT 标注文件，并利用 Ultralytics 算子还原为绝对像素坐标。
    
    返回:
        list of (class_id, x1, y1, x2, y2) 绝对像素坐标。
    """
    boxes = []
    if not txt_path.exists():
        return boxes

    raw_data = []
    with open(txt_path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 5:
                continue
            try:
                cls_id = int(parts[0])
                xc = float(parts[1])
                yc = float(parts[2])
                w = float(parts[3])
                h = float(parts[4])
                raw_data.append((cls_id, xc, yc, w, h))
            except ValueError:
                continue

    if not raw_data:
        return boxes

    cls_ids = [item[0] for item in raw_data]
    xywhn = np.array([[item[1], item[2], item[3], item[4]] for item in raw_data], dtype=np.float64)
    
    # 利用 Ultralytics 算子批量变换到绝对像素 [x1, y1, x2, y2]
    xyxy = xywhn2xyxy(xywhn, w=img_w, h=img_h)
    
    for cls_id, box in zip(cls_ids, xyxy):
        boxes.append((cls_id, float(box[0]), float(box[1]), float(box[2]), float(box[3])))
    return boxes


def parse_geojson_file(
    geojson_path: Path,
    transform=None,
    name_to_id: dict[str, int] | None = None
) -> list[tuple[int, float, float, float, float]]:
    """解析 GeoJSON 格式的标注地理坐标并转换为像素坐标。
    
    返回:
        list of (class_id, x1, y1, x2, y2) 绝对像素坐标。
    """
    if name_to_id is None:
        name_to_id = {}
        
    boxes = []
    with open(geojson_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    features = data.get("features", [])
    for feat in features:
        geom = feat.get("geometry", {})
        props = feat.get("properties", {})
        
        # 提取类别 ID 映射
        cls_name = str(props.get("class_id", props.get("label", props.get("class", "0"))))
        cls_id = int(cls_name) if cls_name.isdigit() else name_to_id.setdefault(cls_name, len(name_to_id))

        gtype = geom.get("type")
        coords = geom.get("coordinates", [])
        
        polys = []
        if gtype == "Polygon" and coords:
            polys.append(coords[0])
        elif gtype == "MultiPolygon":
            for poly in coords:
                if poly:
                    polys.append(poly[0])

        for poly in polys:
            pts = np.array(poly)  # (N, 2)
            if transform:
                px_pts = []
                for pt in pts:
                    col, row = transform.world_to_pixel(pt[0], pt[1])
                    px_pts.append([col, row])
                px_pts = np.array(px_pts)
            else:
                px_pts = pts
            
            x1, y1 = np.min(px_pts, axis=0)
            x2, y2 = np.max(px_pts, axis=0)
            boxes.append((cls_id, float(x1), float(y1), float(x2), float(y2)))
            
    return boxes
