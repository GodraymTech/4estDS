"""YOLO v12 后端(阶段三)。重依赖 ultralytics 延迟导入。"""
from __future__ import annotations

from ..base import BaseDetector, Detection, Detections, Window
from ..registry import register


@register("yolo12")
class Yolo12Detector(BaseDetector):
    """基于 ultralytics 的 YOLO v12 检测器。"""

    def load(self) -> None:
        try:
            from ultralytics import YOLO
        except ImportError as e:  # pragma: no cover - 需重依赖
            raise ImportError(
                "yolo12 后端需要 ultralytics:  pip install '4estds[yolo]'"
            ) from e
        weights = self.weights or "yolo12n.pt"
        self._model = YOLO(weights)

    def predict(self, window: Window) -> Detections:  # pragma: no cover - 需重依赖
        self.ensure_loaded()
        if window.pixels is None:
            raise ValueError("yolo12 后端需要 window.pixels(读窗像素)")
        # TODO(阶段三): 调用 self._model.predict,解析 boxes/conf/cls -> Detections
        raise NotImplementedError("yolo12 真实推理待接入(TODO)")
