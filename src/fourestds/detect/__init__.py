"""推理层(阶段三)。

统一的检测器抽象 + 后端注册表,使上层(切片/后处理/入库)对具体
架构(YOLO12 / RT-DETR)无感知。`mock` 后端用于无 GPU/无网环境的端到端测试。
"""
from .base import BaseDetector, Detection, Detections, Window
from .registry import available_backends, get_detector, register

__all__ = [
    "BaseDetector",
    "Detection",
    "Detections",
    "Window",
    "available_backends",
    "get_detector",
    "register",
]
