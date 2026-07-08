"""FastAPI 应用工厂。

薄壳原则(框架思维)：API 层只负责 HTTP 边界(路由、校验、序列化、错误映射)，
业务一律下沉到 service / worker / db。所有路由挂在 /api/v1 下，便于网关转发与版本演进。
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .. import __codename__, __version__
from .routers import assets, geo, health, jobs, tiles, tracts, uploads

API_PREFIX = "/api/v1"


def _load_local_env() -> None:
    candidates = (Path.cwd() / ".env", Path(__file__).resolve().parents[3] / ".env")
    env_path = next((path for path in candidates if path.exists()), None)
    if env_path is None:
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def create_app() -> FastAPI:
    _load_local_env()
    app = FastAPI(
        title=f"{__codename__} API",
        version=__version__,
        description="红树林单木智能解译平台 — 一张图服务端",
    )

    # CORS: 前端(开发/部署域)可通过环境变量配置，缺省允许本地开发。
    origins = os.environ.get(
        "forestds_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 健康探针不加版本前缀(供编排/网关直接探测)；业务路由统一 /api/v1。
    app.include_router(health.router)
    app.include_router(uploads.router, prefix=API_PREFIX)
    app.include_router(jobs.router, prefix=API_PREFIX)
    app.include_router(tracts.router, prefix=API_PREFIX)
    app.include_router(assets.router, prefix=API_PREFIX)
    app.include_router(geo.router, prefix=API_PREFIX)
    app.include_router(tiles.router, prefix=API_PREFIX)
    return app


app = create_app()
