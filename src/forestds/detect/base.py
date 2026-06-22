"""检测器抽象与结果结构。

设计要点:
- `Window` 是一个切片读窗(全图坐标系的 x,y,w,h 加可选像素)。检测器在读窗
  内部坐标系返回结果,由编排器负责 offset 回全图。
- `Detection` / `Detections` 不依赖 numpy,保证纯 Python 可单测。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace


@dataclass
class Window:
    """一个切片读窗。x,y,w,h 为全图像素坐标;pixels 可选(numpy 数组)。"""
    x: int
    y: int
    w: int
    h: int
    pixels: object | None = None

    @property
    def is_empty(self) -> bool:
        return self.w <= 0 or self.h <= 0


@dataclass
class Detection:
    """单个检测框(x1,y1,x2,y2 为坐标),score 置信度,label 物种类别。"""
    x1: float
    y1: float
    x2: float
    y2: float
    score: float
    label: str = "tree"
    extra: dict = field(default_factory=dict)

    @property
    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    def offset(self, dx: float, dy: float) -> "Detection":
        """返回平移后的新检测(不原地修改)。"""
        return replace(
            self,
            x1=self.x1 + dx, y1=self.y1 + dy,
            x2=self.x2 + dx, y2=self.y2 + dy,
        )

    def as_box(self) -> tuple[float, float, float, float]:
        return (self.x1, self.y1, self.x2, self.y2)


@dataclass
class Detections:
    """一组检测结果与可选元信息。"""
    items: list[Detection] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)

    def offset(self, dx: float, dy: float) -> "Detections":
        """整体平移(将读窗内部坐标还原到全图坐标)。"""
        return Detections([d.offset(dx, dy) for d in self.items], dict(self.meta))

    def boxes_scores(self) -> tuple[list, list]:
        """拆成 (boxes, scores) 供 WBF 等后处理使用。"""
        return [d.as_box() for d in self.items], [d.score for d in self.items]

    def filter_score(self, conf_thr: float) -> "Detections":
        return Detections([d for d in self.items if d.score >= conf_thr], dict(self.meta))


class BaseDetector(ABC):
    """检测器抽象基类。子类实现 load/predict;重依赖延迟导入。"""

    name: str = "base"

    def __init__(self, weights: str | None = None, **kwargs):
        self.weights = weights
        self.kwargs = kwargs
        self._loaded = False

    @abstractmethod
    def load(self) -> None:
        """加载权重/模型。重依赖缺失时应抛出清晰的错误。"""

    @abstractmethod
    def predict(self, window: Window) -> Detections:
        """在读窗内部坐标系返回检测结果。"""

    def predict_batch(self, windows: list[Window]) -> list[Detections]:
        """批量推理。默认逐窗调用 predict;真实后端可重写为单次前向以提升吞吐。

        这是解决“切一下推一下”时间瓶颈的入口:编排器按尺度档/按批收集读窗,
        交由后端一次性推理。
        """
        return [self.predict(w) for w in windows]

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()
            self._loaded = True


def calculate_max_batch_size(
    detector: BaseDetector,
    imgsz: int = 640,
    safety_margin: float = 0.8,
) -> int:
    """通过动态探针（Active Probe）严谨测算出当前显卡在特定模型和输入尺寸下，
    不发生 OOM 的最大安全 batch_size。
    
    参数:
        detector: BaseDetector 检测器适配器实例
        imgsz: 推理时的输入图像尺寸 (如 640 或 1024)
        safety_margin: 安全系数余量，推荐 0.8 左右以抵御显存碎片
    """
    import gc
    import numpy as np

    detector.ensure_loaded()

    # 检测是否能够使用 CUDA
    try:
        import torch
        has_cuda = torch.cuda.is_available()
    except ImportError:
        has_cuda = False

    if not has_cuda:
        return 1

    # 1. 深度清空显存缓存，准备探针
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()

    # 构造虚拟像素矩阵 (numpy) 喂给 Window
    dummy_pixels = np.zeros((imgsz, imgsz, 3), dtype=np.uint8)

    # 2. 指数级探针测试上限 (1, 2, 4, 8, 16, 32, 64, 128...)
    low = 0
    high = 1

    try:
        while True:
            windows = [
                Window(x=0, y=0, w=imgsz, h=imgsz, pixels=dummy_pixels)
                for _ in range(high)
            ]
            _ = detector.predict_batch(windows)

            # 推理成功，记录为下限，并将上限翻倍继续测试
            low = high
            high *= 2

            if high > 512:
                break
    except RuntimeError as e:
        if "out of memory" in str(e).lower():
            pass
        else:
            raise e
    finally:
        gc.collect()
        torch.cuda.empty_cache()

    # 3. 在 [low, high] 区间内进行二分查找精确逼近
    best_bs = low
    if low < high:
        while low <= high:
            mid = (low + high) // 2
            if mid <= 0:
                break
            try:
                windows = [
                    Window(x=0, y=0, w=imgsz, h=imgsz, pixels=dummy_pixels)
                    for _ in range(mid)
                ]
                _ = detector.predict_batch(windows)
                best_bs = mid
                low = mid + 1
            except RuntimeError as e:
                if "out of memory" in str(e).lower():
                    high = mid - 1
                else:
                    raise e
            finally:
                gc.collect()
                torch.cuda.empty_cache()

    # 4. 应用安全系数余量
    return max(1, int(best_bs * safety_margin))
