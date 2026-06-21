"""RT-DETR 后端(阶段三)。

基于 ultralytics 的 RT-DETR 检测器(Transformer 检测头,无 NMS 依赖)。
重依赖延迟导入;接口与 YOLO 后端一致(单窗 + 批量)。
"""
from __future__ import annotations

from ..base import BaseDetector, Detections, Window
from ..registry import register
from .ultralytics_common import build_detections_from_result, ensure_bgr


@register("rtdetr")
class RTDetrDetector(BaseDetector):
    """RT-DETR 检测器(ultralytics)。

    可选 kwargs:
      weights: 权重路径或模型名(默认 rtdetr-l.pt)
      conf:    置信度阈值(默认 0.25)
      imgsz:   推理输入边长(默认 1024,RT-DETR 常用 640/1024)
      device:  'cpu'/'0'/...;None 时由 ultralytics 自动选择
      half:    半精度(GPU 加速)
    """

    def load(self) -> None:
        try:
            from ultralytics import RTDETR
        except ImportError as e:  # pragma: no cover - 需重依赖
            raise ImportError(
                "rtdetr 后端需要 ultralytics:  pip install '4estds[rtdetr]'"
            ) from e
            
        # 强制打通并重置 ultralytics 日志通道，避免其内部覆盖 propagate 属性
        import logging
        ultra_log = logging.getLogger("ultralytics")
        ultra_log.propagate = True
        ultra_log.handlers = []
        
        weights = self.weights or "rtdetr-l.pt"
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
        self._model = RTDETR(weights)

    def _predict_arrays(self, arrays):  # pragma: no cover - 需重依赖
        # RT-DETR 末端无 NMS,不传 iou
        return self._model.predict(
            arrays,
            conf=float(self.kwargs.get("conf", 0.25)),
            imgsz=int(self.kwargs.get("imgsz", 1024)),
            device=self.kwargs.get("device"),
            half=bool(self.kwargs.get("half", False)),
            verbose=bool(self.kwargs.get("verbose", False)),
        )

    def predict(self, window: Window) -> Detections:  # pragma: no cover - 需重依赖
        self.ensure_loaded()
        if window.pixels is None:
            raise ValueError("rtdetr 后端需要 window.pixels(读窗像素)")
        results = self._predict_arrays([ensure_bgr(window.pixels)])
        return build_detections_from_result(results[0], backend="rtdetr")

    def predict_batch(self, windows: list[Window]) -> list[Detections]:  # pragma: no cover
        self.ensure_loaded()
        if any(w.pixels is None for w in windows):
            raise ValueError("rtdetr 后端批量推理需要每个 window.pixels")
        if not windows:
            return []
        results = self._predict_arrays([ensure_bgr(w.pixels) for w in windows])
        return [build_detections_from_result(r, backend="rtdetr") for r in results]
