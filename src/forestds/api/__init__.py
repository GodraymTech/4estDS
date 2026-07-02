"""HTTP API 层 (FastAPI 薄壳)。

职责仅限 HTTP 边界：路由、参数校验、序列化、错误映射；
业务下沉到 service/worker/db。入口: ``from forestds.api.main import app``。
"""
from __future__ import annotations
