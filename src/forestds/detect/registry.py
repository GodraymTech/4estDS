"""检测器后端注册表。

通过 `@register("name")` 装饰器注册后端类;`get_detector(arch)` 延迟导入并实例化。
内置后端: ultralytics (通用 YOLO & RT-DETR)。
"""
from __future__ import annotations

import importlib
from typing import Callable

from .base import BaseDetector

_REGISTRY: dict[str, type[BaseDetector]] = {}

# 内置后端 -> 所在模块(延迟导入,避免未装重依赖时导入失败)
_KNOWN: dict[str, str] = {
    "ultralytics": "forestds.detect.backends.ultralytics",
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


def resolve_weights_path(weights: str) -> str:
    """根据权重模糊特征字在 paths.models_dir() 中进行模糊搜索，返回物理全路径。"""
    from pathlib import Path
    path = Path(weights)
    if path.exists():
        return str(path.resolve())

    # 从 paths.models_dir() 中检索
    from .. import paths
    try:
        m_dir = paths.models_dir()
    except Exception:
        return weights

    if m_dir.exists():
        candidates = []
        for p in m_dir.iterdir():
            if p.is_file():
                # 模糊匹配：忽略大小写，包含 weights
                if weights.lower() in p.name.lower():
                    candidates.append(p)
        
        if len(candidates) == 1:
            from loguru import logger
            logger.info("[detect] 模糊搜索权重 '{}' 匹配到唯一模型: {}", weights, candidates[0].name)
            return str(candidates[0].resolve())
        elif len(candidates) > 1:
            from loguru import logger
            candidates.sort(key=lambda x: x.name)
            names = [c.name for c in candidates]
            logger.warning(
                "[detect] 权重特征 '{}' 模糊匹配到多个候选: {}, 默认使用第一个: {}",
                weights, names, names[0]
            )
            return str(candidates[0].resolve())

    return weights


def get_detector(arch: str, **kwargs) -> BaseDetector:
    """按名获取检测器实例。未注册时尝试延迟导入其模块。"""
    if "weights" in kwargs and kwargs["weights"]:
        kwargs["weights"] = resolve_weights_path(kwargs["weights"])

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

