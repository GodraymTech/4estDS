"""YOLO v12 后端(阶段三)。

基于 ultralytics 的 YOLO 检测器。重依赖(ultralytics/torch)延迟导入,
缺失时报出清晰的安装指引。支持单窗 predict 与批量 predict_batch(单次前向)。
"""
from __future__ import annotations

from ..base import BaseDetector, Detections, Window
from ..registry import register
from .ultralytics_common import build_detections_from_result, ensure_bgr


@register("yolo12")
class Yolo12Detector(BaseDetector):
    """YOLO v12 检测器(ultralytics)。

    可选 kwargs:
      weights: 权重路径或模型名(默认 yolo12n.pt)
      conf:    置信度阈值(默认 0.25)
      iou:     NMS IoU 阈值(默认 0.7)
      imgsz:   推理输入边长(默认 1024)
      device:  'cpu'/'0'/...;None 时由 ultralytics 自动选择
      half:    半精度(GPU 加速)
    """

    def load(self) -> None:
        try:
            from ultralytics import YOLO
        except ImportError as e:  # pragma: no cover - 需重依赖
            raise ImportError(
                "yolo12 后端需要 ultralytics:  pip install '4estds[yolo]'"
            ) from e
            
        # 强制打通并重置 ultralytics 日志通道，避免其内部覆盖 propagate 属性
        import logging
        ultra_log = logging.getLogger("ultralytics")
        ultra_log.propagate = True
        ultra_log.handlers = []
        
        weights = self.weights or "yolo12n.pt"
        if "/" not in weights and "\\" not in weights:
            import os
            from ... import paths
            weights = os.path.join(str(paths.models_dir()), weights)

        # 检查自定义本地权重文件是否存在，若缺失则抛出友好错误
        import os
        base = os.path.basename(weights)
        # is_official = (
        #     base.startswith(("yolo12", "rtdetr"))
        #     and base.endswith(".pt")
        #     and len(base.split("-")) <= 2
        #     and not any(char.isupper() for char in base)
        # )
        if not os.path.exists(weights):
            raise FileNotFoundError(
                f"找不到模型权重: {weights}\n"
                f"请确保路径正确, 或手动下载: 'cp ~/.4estDS/models/{base} .4estDS/models/{base}'. 然后再重新运行。"
            )
        self._model = YOLO(weights)

    def _predict_arrays(self, arrays):  # pragma: no cover - 需重依赖
        return self._model.predict(
            arrays,
            conf=float(self.kwargs.get("conf", 0.25)),
            iou=float(self.kwargs.get("iou", 0.7)),
            imgsz=int(self.kwargs.get("imgsz", 1024)),
            device=self.kwargs.get("device"),
            half=bool(self.kwargs.get("half", False)),
            verbose=bool(self.kwargs.get("verbose", False)),
        )

    def predict(self, window: Window) -> Detections:  # pragma: no cover - 需重依赖
        self.ensure_loaded()
        if window.pixels is None:
            raise ValueError("yolo12 后端需要 window.pixels(读窗像素)")
        results = self._predict_arrays([ensure_bgr(window.pixels)])
        return build_detections_from_result(results[0], backend="yolo12")

    def predict_batch(self, windows: list[Window]) -> list[Detections]:  # pragma: no cover
        self.ensure_loaded()
        if any(w.pixels is None for w in windows):
            raise ValueError("yolo12 后端批量推理需要每个 window.pixels")
        if not windows:
            return []
        results = self._predict_arrays([ensure_bgr(w.pixels) for w in windows])
        return [build_detections_from_result(r, backend="yolo12") for r in results]
