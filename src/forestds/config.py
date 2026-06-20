"""分层配置加载。

优先级(从低到高): 包内 ``configs/default.yaml`` -> ``~/.4estDS/config.yaml``
-> 环境变量 ``forestds_<SECTION>__<KEY>`` -> 代码传入的 overrides。

设计上对应 pydantic-settings 的分层语义;为保证无额外依赖也能运行,
这里用标准库 + PyYAML 实现。本地装了 pydantic-settings 后可平滑替换。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import paths

_ENV_PREFIX = "forestds_"


def _packaged_default() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "configs" / "default.yaml"


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _coerce(value: str) -> Any:
    """把环境变量字符串尽量转为 bool/int/float。"""
    low = value.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _env_overrides() -> dict:
    """解析 forestds_SECTION__KEY=value 形式的环境变量。"""
    out: dict[str, dict[str, Any]] = {}
    for key, val in os.environ.items():
        if not key.startswith(_ENV_PREFIX) or key == "forestds_HOME":
            continue
        body = key[len(_ENV_PREFIX):]
        if "__" not in body:
            continue
        section, _, leaf = body.partition("__")
        out.setdefault(section.lower(), {})[leaf.lower()] = _coerce(val)
    return out


@dataclass
class Settings:
    """托管所有配置的扁平容器。各节点为普通 dict,便于演进与测试。"""

    data: dict[str, Any] = field(default_factory=dict)
    _flat: dict[str, Any] = field(default_factory=dict, init=False)

    def __post_init__(self):
        self._flat = {}
        duplicates = set()

        def flatten(d: dict):
            for k, v in d.items():
                if isinstance(v, dict):
                    flatten(v)
                else:
                    if k in self._flat:
                        duplicates.add(k)
                    else:
                        self._flat[k] = v

        flatten(self.data)
        for dup in duplicates:
            self._flat.pop(dup, None)

    def section(self, name: str) -> dict[str, Any]:
        return dict(self.data.get(name, {}))

    def get(self, path: str, default: Any = None) -> Any:
        # 1. 优先作为点分隔路径查找
        cur: Any = self.data
        found = True
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                found = False
                break
            cur = cur[part]
        if found:
            return cur

        # 2. 如果没找到且没有点分隔，尝试从扁平唯一叶子映射中获取
        if "." not in path and path in self._flat:
            return self._flat[path]

        return default


def load_settings(overrides: dict | None = None) -> Settings:
    """按优先级合并生成 Settings。"""
    merged: dict[str, Any] = {}

    default_path = _packaged_default()
    if default_path.exists():
        merged = yaml.safe_load(default_path.read_text(encoding="utf-8")) or {}

    user_path = paths.config_file()
    if user_path.exists():
        user_cfg = yaml.safe_load(user_path.read_text(encoding="utf-8")) or {}
        merged = _deep_merge(merged, user_cfg)

    merged = _deep_merge(merged, _env_overrides())

    if overrides:
        merged = _deep_merge(merged, overrides)

    return Settings(data=merged)
