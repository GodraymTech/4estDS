"""细粒度树种分类适配器（树种精检）。

职责：
  - 承接 2cls 目标检测（TREE/GG）的产出，对 TREE 标签单木做进一步的细粒度分类；
  - 支持 YOLO 分类头模型（权重由 classify.weights 指定）；
  - 类别到树种名称的映射与低置信度兜底项均来自配置 classify.species_map（唯一来源）；
  - 替换 Detection 的 label 字段，保持下游 DB、GIS 导出、报告与交互复核一致性。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from loguru import logger as log

from .backends.ultralytics_common import ensure_bgr
from .base import Detection
from .registry import resolve_weights_path

if TYPE_CHECKING:
    from ..engine.sources import ImageSource


class SpeciesClassifier:
    """通用细粒度树种分类器。

    所有参数由调用方显式提供（生产路径来自 classify.* 配置），代码内不保留默认权重或映射。
    """

    def __init__(
        self,
        weights: str,
        *,
        species_map: dict[str, str],
        conf_threshold: float,
        batch_size: int,
        imgsz: int | None = None,
        device: str | None = None,
        half: bool | None = None,
    ):
        if "TREE" not in species_map:
            raise ValueError("classify.species_map 必须包含 TREE 兜底项")
        self.weights = weights
        self.conf_threshold = conf_threshold
        self.batch_size = batch_size
        self.imgsz = imgsz
        self.device = device
        self.half = half
        self.species_map = dict(species_map)
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

        resolved_path = resolve_weights_path(self.weights)
        if not os.path.exists(resolved_path):
            raise FileNotFoundError(
                f"找不到树种分类模型权重: {resolved_path}\n"
                f"请确保权重已放置在 .4estDS/models/ 目录，并在 classify.weights 中指定正确文件名。"
            )

        self._model = YOLO(resolved_path)
        log.info("加载树种精检分类模型: {}", resolved_path)

    def predict_crops(
        self,
        crops: list[np.ndarray],
    ) -> list[tuple[str, float]]:
        """批量对裁剪的单木图像块进行树种分类预测。

        裁剪块与检测分支共用 ensure_bgr 预处理（RGB -> BGR、dtype 归一为 uint8）：
        ultralytics 对 numpy 输入不做通道转换，直接送入 RGB 会导致 R/B 通道反转。

        Returns:
            list of (mapped_species_label, confidence)
        """
        if not crops:
            return []
        self.load()
        crops = [ensure_bgr(c) for c in crops]

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

                # 若分类置信度低于阈值，则使用 TREE 兜底项
                if top1_conf < self.conf_threshold:
                    mapped_name = "TREE"
                else:
                    from ..species import normalize_species_code
                    mapped_name = normalize_species_code(raw_name)

                results.append((mapped_name, top1_conf))

        return results


def _require(settings: Any, key: str) -> Any:
    """读取必需配置项；缺失时给出明确错误，而非静默回退到代码默认值。"""
    value = settings.get(key)
    if value is None or value == "":
        raise ValueError(f"树种精检缺少必需配置项: {key}")
    return value


def _build_classifier(settings: Any) -> SpeciesClassifier:
    """依据 classify.* 配置构建分类器。"""
    imgsz = settings.get("classify.imgsz")
    return SpeciesClassifier(
        _require(settings, "classify.weights"),
        species_map=dict(_require(settings, "classify.species_map")),
        conf_threshold=float(_require(settings, "classify.conf_threshold")),
        batch_size=int(_require(settings, "classify.batch_size")),
        imgsz=int(imgsz) if imgsz else None,
        device=settings.get("detect.device"),
    )


def refine_species_with_classifier(
    detections: list[Detection] | Any,
    image_path: str,
    *,
    settings: Any,
    classifier: SpeciesClassifier | None = None,
    chunk_size: int = 256,
) -> dict[str, int]:
    """对 detections 中 label 为 TREE 的单木框裁剪并做细粒度分类，原地替换 label 为具体树种名称。

    GG 标签框保持原样不变。

    Args:
        detections: run_inference 产出的检测框列表或 Detections 容器 (像素坐标)。
        image_path: 原始影像路径 (TIFF/JPG/PNG)。
        settings: 全局配置对象，需包含 classify.* 必需项（weights、species_map、conf_threshold、batch_size、pad_ratio）。
        classifier: 可选复用的分类器实例；为空时依据配置构建。
        chunk_size: 裁剪与推理批次大小，防止显存与内存暴涨。

    Returns:
        物种统计字典，例如 {"秋茄": 42, "其他红树": 3, "GG": 2}
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
    pad_ratio = float(_require(settings, "classify.pad_ratio"))
    if classifier is None:
        classifier = _build_classifier(settings)

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
                    d.label = "TREE"

            if crops:
                from ..species import normalize_species_code
                predictions = classifier.predict_crops(crops)
                for det_idx, (sp_name, conf) in zip(valid_batch_indices, predictions):
                    d = det_list[det_idx]
                    d.label = normalize_species_code(sp_name)
                    if d.extra is None:
                        d.extra = {}
                    d.extra["cls_score"] = conf

    # 4. 统计结果
    counts = {}
    for d in det_list:
        counts[d.label] = counts.get(d.label, 0) + 1

    log.info(
        "【树种精检完成】细分类单木数={} 物种分布={}",
        len(target_indices),
        counts,
    )
    return counts
