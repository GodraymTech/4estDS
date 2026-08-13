"""健康探针端点(不加版本前缀，供编排/网关/负载均衡直接探测)。

- GET /healthz  -> 存活探针(liveness)：进程存活即 200，不依赖外部服务，避免误杀。
- GET /health   -> 就绪探针(readiness)：附带存储/数据库探测结果，供上游判断是否分流。

设计: liveness 必须轻量且无依赖；readiness 可治理依赖，但依赖抖动不应重启进程(故分开)。
"""
from __future__ import annotations

import os
from fastapi import APIRouter, Depends, Request

from ... import __codename__, __version__
from ..deps import get_db_url, get_storage_dep

router = APIRouter(tags=["health"])


@router.get("/healthz", summary="存活探针(liveness)")
def healthz(request: Request) -> dict:
    """进程存活即返回 200，返回后端监听端口与环境元数据。"""
    env_port = os.environ.get("PORT_API")
    resolved_port = int(env_port) if env_port and env_port.isdigit() else (request.url.port or 80)
    return {
        "status": "ok",
        "service": __codename__,
        "version": __version__,
        "port": resolved_port,
        "env": os.environ.get("ENV_MODE", "prod"),
    }


@router.get("/health", summary="就绪探针(readiness)")
def health(
    db_url: str | None = Depends(get_db_url),
    storage=Depends(get_storage_dep),
) -> dict:
    """附带存储/数据库探测。任一依赖不可达时 status=degraded(仍 200，供上游自行判断)。"""
    checks: dict[str, str] = {}

    # 存储探测: exists 对任意 key 返回 bool；不抛异常即视为可达。
    try:
        storage.exists("__healthcheck__")
        checks["storage"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["storage"] = f"error: {exc}"

    # 数据库探测: 轻量只读查询(空库也应成功返回空列表)。
    try:
        from ...db import reader

        reader.list_tracts(url=db_url)
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {exc}"

    ready = all(v == "ok" for v in checks.values())
    return {
        "status": "ok" if ready else "degraded",
        "service": __codename__,
        "version": __version__,
        "checks": checks,
    }
