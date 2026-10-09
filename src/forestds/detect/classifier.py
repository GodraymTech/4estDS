"""细粒度树种分类适配器（树种精检）。

职责：
  - 承接 2cls 目标检测（TREE/GG）的产出，对 TREE 标签单木做进一步的细粒度 7 分类；
  - 支持 YOLO 分类头模型（如 m03-yolo11l-7cls-SOTA.pt）；
  - 将英文缩写（QQ, HHL, THS, ML, BGR, WBHS, TREE）映射为规范中文树种名称及 OTHER 兜底；
  - 替换 Detection 的 label 字段，保持下游 DB、GIS 导出、报告与交互复核一致性。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from loguru import logger as log

from .base import Detection
from .registry import resolve_weights_path

if TYPE_CHECKING:
    from ..engine.sources import ImageSource

# 默认树种代码映射表
DEFAULT_SPECIES_MAP: dict[str, str] = {
    "QQ": "秋茄",
    "HHL": "红海榄",
    "THS": "桐花树",
    "ML": "木榄",
    "BGR": "白骨壤",
    "WBHS": "无瓣海桑",
    "TREE": "OTHER",
    "GG": "GG",
}


class SpeciesClassifier:
    """通用细粒度树种分类器。"""

    def __init__(
        self,
        weights: str | None = None,
        *,
        conf_threshold: float = 0.25,
        batch_size: int = 128,
        imgsz: int | None = None,
        device: str | None = None,
        half: bool | None = None,
        species_map: dict[str, str] | None = None,
    ):
        self.weights = weights
        self.conf_threshold = conf_threshold
        self.batch_size = batch_size
        self.imgsz = imgsz
        self.device = device
        self.half = half
        self.species_map = dict(DEFAULT_SPECIES_MAP)
        if species_map:
            self.species_map.update(species_map)
        self._model = None

    def load(self) -> None:
        """加载 Ultralytics 分类模型权重。"""
        if self._model is not None:
            return

        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise ImportError("树种分类需要 ultralytics: pip install '4estds[yolo]'") from exc

        # 打通 ultralytics 日志
        import logging
        ultra_log = logging.getLogger("ultralytics")
        ultra_log.propagate = True
        ultra_log.handlers = []

        weights_str = self.weights or "m03-yolo11l-7cls-SOTA.pt"
        resolved_path = resolve_weights_path(weights_str)
        if not os.path.exists(resolved_path):
            raise FileNotFoundError(
                f"找不到树种分类模型权重: {resolved_path}\n"
                f"请确保权重已放置在 .4estDS/models/ 目录或配置中指定了正确路径。"
            )

        self._model = YOLO(resolved_path)
        log.info("加载树种精检分类模型: {}", resolved_path)

    def predict_crops(
        self,
        crops: list[np.ndarray],
    ) -> list[tuple[str, float]]:
        """批量对裁剪的单木图像块进行树种分类预测。

        Returns:
            list of (mapped_species_label, confidence)
        """
        if not crops:
            return []
        self.load()

        device = self.device
        if device is None:
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"

        half_val = self.half
        if half_val is None:
            half_val = device == "cuda"

        predict_kwargs: dict[str, Any] = {
            "device": device,
            "half": half_val,
            "verbose": False,
        }
        if self.imgsz:
            predict_kwargs["imgsz"] = int(self.imgsz)

        results: list[tuple[str, float]] = []
        for i in range(0, len(crops), self.batch_size):
            batch = crops[i : i + self.batch_size]
            preds = self._model.predict(
                batch,
                **predict_kwargs,
            )
            for r in preds:
                if hasattr(r, "probs") and r.probs is not None:
                    top1_idx = int(r.probs.top1)
                    top1_conf = float(r.probs.top1conf)
                    names_dict = getattr(r, "names", {})
                    if isinstance(names_dict, dict):
                        raw_name = str(names_dict.get(top1_idx, "OTHER"))
                    elif isinstance(names_dict, (list, tuple)) and top1_idx < len(names_dict):
                        raw_name = str(names_dict[top1_idx])
                    else:
                        raw_name = str(top1_idx)
                else:
                    raw_name = "OTHER"
                    top1_conf = 0.0

                # 若分类置信度低于阈值，则使用 OTHER 兜底
                if top1_conf < self.conf_threshold:
                    mapped_name = self.species_map.get("TREE", "OTHER")
                else:
                    mapped_name = self.species_map.get(raw_name.upper(), raw_name)

                results.append((mapped_name, top1_conf))

        return results


def refine_species_with_classifier(
    detections: list[Detection] | Any,
    image_path: str,
    *,
    settings: Any = None,
    arch: str = "ultralytics",
    classifier: SpeciesClassifier | None = None,
    chunk_size: int = 256,
) -> dict[str, int]:
    """对 detections 中 label 为 TREE 的单木框裁剪并做细粒度分类，原地替换 label 为具体树种名称。

    GG 标签框保持原样不变。

    Args:
        detections: run_inference 产出的检测框列表或 Detections 容器 (像素坐标)。
        image_path: 原始影像路径 (TIFF/JPG/PNG)。
        settings: 全局配置对象。
        arch: 当前使用的检测器架构名。
        classifier: 可选复用的分类器实例。
        chunk_size: 裁剪与推理批次大小，防止显存与内存暴涨。

    Returns:
        物种统计字典，例如 {"秋茄": 42, "红海榄": 15, "OTHER": 3, "GG": 2}
    """
    det_list = detections.items if hasattr(detections, "items") and isinstance(detections.items, list) else detections
    if not det_list:
        return {}

    # 1. 过滤出需要进一步细化树种的目标索引（排除已是 GG 的死树）
    target_indices: list[int] = []
    for idx, d in enumerate(det_list):
        lbl = (d.label or "").strip().upper()
        if lbl in ("TREE", "0", ""):
            target_indices.append(idx)

    if not target_indices:
        log.info("未发现待细化的 TREE 类别检测框，跳过树种精检分类。")
        counts: dict[str, int] = {}
        for d in detections:
            counts[d.label] = counts.get(d.label, 0) + 1
        return counts

    # 2. 初始化分类器
    pad_ratio = 0.1
    if settings is not None:
        pad_ratio = float(settings.get("classify.pad_ratio", 0.1))

    if classifier is None:
        cls_weights = "m03-yolo11l-7cls-SOTA.pt"
        conf_thr = 0.25
        b_size = 128
        imgsz = None
        dev = None
        s_map = None

        if settings is not None:
            cls_weights = (
                settings.get(f"detect.models.{arch}.cls_weights")
                or settings.get("classify.weights")
                or cls_weights
            )
            conf_thr = float(
                settings.get("classify.conf_threshold", settings.get("detect.conf_threshold", 0.25))
            )
            b_size = int(settings.get("classify.batch_size", 128))
            imgsz = settings.get("classify.imgsz", None)
            dev = settings.get("detect.device", None)
            s_map = settings.get("classify.species_map", None)

        classifier = SpeciesClassifier(
            weights=cls_weights,
            conf_threshold=conf_thr,
            batch_size=b_size,
            imgsz=imgsz,
            device=dev,
            species_map=s_map,
        )

    # 3. 按 chunk 读取窗口裁剪并批量预测
    from ..engine.sources import RasterImageSource

    with RasterImageSource(image_path) as reader:
        img_w, img_h = reader.width, reader.height

        for start_idx in range(0, len(target_indices), chunk_size):
            batch_target_indices = target_indices[start_idx : start_idx + chunk_size]
            crops: list[np.ndarray] = []
            valid_batch_indices: list[int] = []

            for det_idx in batch_target_indices:
                d = det_list[det_idx]
                bw = max(1.0, float(d.x2 - d.x1))
                bh = max(1.0, float(d.y2 - d.y1))
                pad_w = bw * pad_ratio
                pad_h = bh * pad_ratio

                x0 = max(0, min(int(round(d.x1 - pad_w)), img_w - 1))
                y0 = max(0, min(int(round(d.y1 - pad_h)), img_h - 1))
                x1 = max(x0 + 1, min(int(round(d.x2 + pad_w)), img_w))
                y1 = max(y0 + 1, min(int(round(d.y2 + pad_h)), img_h))
                w = x1 - x0
                h = y1 - y0

                crop = reader.read_window(x0, y0, w, h)
                if crop is not None and crop.size > 0:
                    crops.append(crop)
                    valid_batch_indices.append(det_idx)
                else:
                    # 无法读取有效像素，回退为 OTHER 兜底
                    d.label = classifier.species_map.get("TREE", "OTHER")

            if crops:
                predictions = classifier.predict_crops(crops)
                for det_idx, (sp_name, conf) in zip(valid_batch_indices, predictions):
                    d = det_list[det_idx]
                    d.label = sp_name
                    if d.extra is None:
                        d.extra = {}
                    d.extra["cls_score"] = conf

    # 4. 统计结果
    counts: dict[str, int] = {}
    for d in det_list:
        counts[d.label] = counts.get(d.label, 0) + 1

    log.info(
        "【树种精检完成】细分类单木数={} 物种分布={}",
        len(target_indices),
        counts,
    )
    return counts
