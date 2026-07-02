"""FastAPI 依赖提供 (Dependency Injection)。

集中提供跨路由共享的运行时依赖：Settings、db_url、Storage。
单例 Settings 避免每请求重新加载配置(性能)；保持无状态读取。
"""
from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def get_settings():
    """进程内单例 Settings。"""
    from .. import paths
    from ..config import load_settings

    paths.ensure_home()
    return load_settings()


def get_db_url() -> str | None:
    """当前数据库 URL(None 表示默认本地 sqlite)。"""
    return get_settings().get("url", None)


def get_storage_dep():
    """存储后端依赖。"""
    from .storage import get_storage

    return get_storage(get_settings())
