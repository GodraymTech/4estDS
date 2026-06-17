"""RT-DETR 后端(阶段三)。重依赖 ultralytics 延迟导入。"""
from __future__ import annotations

from ..base import BaseDetector, Detections, Window
from ..registry import register


@register("rtdetr")
class RTDetrDetector(BaseDetector):
    """基于 ultralytics 的 RT-DETR 检测器。"""

    def load(self) -> None:
        try:
            from ultralytics import RTDETR
        except ImportError as e:  # pragma: no cover - 需重依赖
            raise ImportError(
                "rtdetr 后端需要 ultralytics:  pip install '4estds[rtdetr]'"
            ) from e
        weights = self.weights or "rtdetr-l.pt"
        self._model = RTDETR(weights)

    def predict(self, window: Window) -> Detections:  # pragma: no cover - 需重依赖
        self.ensure_loaded()
        if window.pixels is None:
            raise ValueError("rtdetr 后端需要 window.pixels(读窗像素)")
        # TODO(阶段三): 调用 self._model.predict,解析 boxes/conf/cls -> Detections
        raise NotImplementedError("rtdetr 真实推理待接入(TODO)")
