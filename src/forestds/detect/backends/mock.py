"""内置 mock 检测器。

用于 CLI/API/测试环境的端到端冒烟验证，不依赖模型权重、GPU 或像素内容。
"""
from __future__ import annotations

from ..base import BaseDetector, Detection, Detections, Window
from ..registry import register


@register("mock")
class MockDetector(BaseDetector):
    """按读窗中心生成一个确定性检测框的轻量后端。"""

    def load(self) -> None:
        self._loaded = True

    def predict(self, window: Window) -> Detections:
        if window.is_empty:
            return Detections([])

        score = float(self.kwargs.get("score", 0.8))
        label = str(self.kwargs.get("label", "tree"))
        size = max(12.0, min(float(window.w), float(window.h)) * 0.08)
        half = size / 2.0
        cx = float(window.w) / 2.0
        cy = float(window.h) / 2.0

        return Detections(
            [
                Detection(
                    x1=max(0.0, cx - half),
                    y1=max(0.0, cy - half),
                    x2=min(float(window.w), cx + half),
                    y2=min(float(window.h), cy + half),
                    score=score,
                    label=label,
                    extra={"mock": True},
                )
            ],
            {"backend": self.name},
        )
