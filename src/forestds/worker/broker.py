"""Dramatiq broker 装配 (Redis)。

12-factor: 通过环境变量 ``REDIS_URL`` 注入连接串。
本模块 import 时即完成 broker 装配与 set_broker，**必须在任何 actor 声明之前被导入**
(actors.py 首行即 import 本模块)。这是 Dramatiq 的标准装配模式。
"""
from __future__ import annotations

import os

import dramatiq
from dramatiq.brokers.redis import RedisBroker

DEFAULT_REDIS_URL = "redis://localhost:6379/0"


def build_broker() -> RedisBroker:
    """从环境变量构造 Redis broker。"""
    url = os.environ.get("REDIS_URL", DEFAULT_REDIS_URL)
    return RedisBroker(url=url)


# import 时装配全局 broker。
broker = build_broker()
dramatiq.set_broker(broker)
