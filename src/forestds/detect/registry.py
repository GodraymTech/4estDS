"""检测器后端注册表。

通过 `@register("name")` 装饰器注册后端类;`get_detector(arch)` 延迟导入并实例化。
内置后端:yolo12 / rtdetr / mock。
"""
from __future__ import annotations

import importlib
from typing import Callable

from .base import BaseDetector

_REGISTRY: dict[str, type[BaseDetector]] = {}

# 内置后端 -> 所在模块(延迟导入,避免未装重依赖时导入失败)
_KNOWN: dict[str, str] = {
    "yolo12": "forestds.detect.backends.yolo12",
    "rtdetr": "forestds.detect.backends.rtdetr",
}


def register(name: str) -> Callable[[type[BaseDetector]], type[BaseDetector]]:
    """类装饰器:把检测器后端注册到全局表。"""
    def deco(cls: type[BaseDetector]) -> type[BaseDetector]:
        cls.name = name
        _REGISTRY[name] = cls
        return cls
    return deco


def available_backends() -> list[str]:
    """返回已知后端名(包括尚未导入的内置后端)。"""
    return sorted(set(_REGISTRY) | set(_KNOWN))


def get_detector(arch: str, **kwargs) -> BaseDetector:
    """按名获取检测器实例。未注册时尝试延迟导入其模块。"""
    if arch not in _REGISTRY:
        module = _KNOWN.get(arch)
        if module is None:
            raise ValueError(
                f"未知检测器后端: {arch!r};可用: {available_backends()}"
            )
        importlib.import_module(module)  # 触发该模块里的 @register
    if arch not in _REGISTRY:
        raise RuntimeError(f"后端 {arch!r} 导入后仍未注册(检查 @register 装饰器)")
    return _REGISTRY[arch](**kwargs)
