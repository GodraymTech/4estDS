"""模型适配器层（Model adapter layer）。

职责：
  - 将各推理后端（Ultralytics YOLO12 / RT-DETR 等）统一封装为 BaseDetector 接口
  - 通过注册表（registry.py）实现按名称动态加载，上层无需 import 具体后端
  - 提供 Detection / Detections / Window 等核心数据结构

不感知（严禁引入）：
  - 数据库（db/）、文件系统（paths.py）、配置（config.py）
  - tasks/、engine/ 的上层编排逻辑

调用关系（单向，不可逆）：
  detect/ ← engine/（engine 是唯一合法调用方；tasks/ 间接通过 engine 使用）
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
