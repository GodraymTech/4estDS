"""Ultralytics 后端(YOLO / RT-DETR 通用)。

基于 ultralytics 的 YOLO 与 RT-DETR 检测器。重依赖延迟导入,
支持单窗 predict 与批量 predict_batch(单次前向)。
"""
from __future__ import annotations

from ..base import BaseDetector, Detections, Window
from ..registry import register
from .ultralytics_common import build_detections_from_result, ensure_bgr
from loguru import logger as log


@register("ultralytics")
class UltralyticsDetector(BaseDetector):
    """通用 Ultralytics 检测器，自适应兼容 YOLO 与 RT-DETR 后端。

    可选 kwargs:
      weights: 权重路径或模型名(默认 yolo12n.pt)
      conf:    置信度阈值(默认 0.25)
      iou:     NMS IoU 阈值(默认 0.7，仅 YOLO 生效)
      imgsz:   推理输入边长(默认 1024)
      device:  'cpu'/'0'/...;None 时由 ultralytics 自动选择
      half:    半精度(GPU 加速)
    """

    def load(self) -> None:
        # 自适应根据权重或名称判断是否是 RT-DETR
        weights = self.weights or "yolo12n.pt"
        is_rtdetr = "rtdetr" in weights.lower()

        try:
            if is_rtdetr:
                from ultralytics import RTDETR as ModelClass
            else:
                from ultralytics import YOLO as ModelClass
        except ImportError as e:  # pragma: no cover
            backend_name = "rtdetr" if is_rtdetr else "yolo"
            raise ImportError(
                f"{backend_name} 需要 ultralytics: pip install '4estds[yolo]'"
            ) from e
            
        # 强制打通并重置 ultralytics 日志通道，避免其内部覆盖 propagate 属性
        import logging
        ultra_log = logging.getLogger("ultralytics")
        ultra_log.propagate = True
        ultra_log.handlers = []
        
        if "/" not in weights and "\\" not in weights:
            import os
            from ... import paths
            weights = os.path.join(str(paths.models_dir()), weights)

        # 检查自定义本地权重文件是否存在，若缺失则抛出友好错误
        import os
        if not os.path.exists(weights):
            raise FileNotFoundError(
                f"找不到模型权重: {weights}\n"
                f"请确保路径正确, 或联系项目维护人员。"
            )
        self._model = ModelClass(weights)
        self._is_rtdetr = is_rtdetr

    def _predict_arrays(self, arrays):  # pragma: no cover
        device = self.kwargs.get("device")
        if device is None:
            try:
                import torch
                if torch.cuda.is_available():
                    device = "cuda"
                else:
                    device = "cpu"
            except ImportError:
                device = "cpu"

        # 如果是 GPU 推理，且配置中未指定 half，则默认启用半精度加速
        half_val = bool(self.kwargs.get("half", False))
        if device == "cuda" and "half" not in self.kwargs:
            half_val = True

        if self.kwargs.get("_last_device") != device:
            self.kwargs["_last_device"] = device
            log.info("Ultralytics 推理设备: device={} half={}", device, half_val)

        predict_kwargs = {
            "conf": float(self.kwargs.get("conf", 0.25)),
            "imgsz": int(self.kwargs.get("imgsz", 1024)),
            "device": device,
            "half": half_val,
            "verbose": bool(self.kwargs.get("verbose", False)),
        }
        # RT-DETR 末端无 NMS，不传 iou
        if not self._is_rtdetr:
            predict_kwargs["iou"] = float(self.kwargs.get("iou", 0.7))

        return self._model.predict(arrays, **predict_kwargs)

    def predict(self, window: Window) -> Detections:  # pragma: no cover
        self.ensure_loaded()
        if window.pixels is None:
            raise ValueError(f"{self.name} 后端需要 window.pixels(读窗像素)")
        results = self._predict_arrays([ensure_bgr(window.pixels)])
        return build_detections_from_result(results[0], backend=self.name)

    def predict_batch(self, windows: list[Window]) -> list[Detections]:  # pragma: no cover
        self.ensure_loaded()
        if any(w.pixels is None for w in windows):
            raise ValueError(f"{self.name} 后端批量推理需要每个 window.pixels")
        if not windows:
            return []
        results = self._predict_arrays([ensure_bgr(w.pixels) for w in windows])
        return [build_detections_from_result(r, backend=self.name) for r in results]
