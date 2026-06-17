"""Mock 检测后端——无 GPU/无网环境下的端到端测试用。

不加载任何模型:构造时传入一组全图"真实树"(cx, cy, size),
predict() 返回落在当前读窗内的树(转为读窗内部坐标)。
这样可验证:重叠切片 -> 同一棵树多次检出 -> WBF 正确去重。
"""
from __future__ import annotations

from ..base import BaseDetector, Detection, Detections, Window
from ..registry import register


@register("mock")
class MockDetector(BaseDetector):
    """确定性合成检测器。trees: 全图坐标的 (cx, cy, size[, label[, score]])。"""

    def __init__(self, trees: list[tuple] | None = None, score: float = 0.9, **kwargs):
        super().__init__(**kwargs)
        self.trees = trees or []
        self.default_score = score

    def load(self) -> None:
        # 无需加载任何权重
        return None

    def predict(self, window: Window) -> Detections:
        self.ensure_loaded()
        items: list[Detection] = []
        if window.is_empty:
            return Detections(items, {"backend": "mock"})
        wx0, wy0 = window.x, window.y
        wx1, wy1 = window.x + window.w, window.y + window.h
        for t in self.trees:
            cx, cy, size = t[0], t[1], t[2]
            label = t[3] if len(t) > 3 else "tree"
            score = t[4] if len(t) > 4 else self.default_score
            # 只检出中心落在读窗内的树
            if not (wx0 <= cx < wx1 and wy0 <= cy < wy1):
                continue
            half = size / 2.0
            # 转为读窗内部坐标
            lx, ly = cx - wx0, cy - wy0
            items.append(Detection(
                x1=lx - half, y1=ly - half,
                x2=lx + half, y2=ly + half,
                score=score, label=label,
            ))
        return Detections(items, {"backend": "mock", "window": (wx0, wy0)})
