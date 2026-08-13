"""FastAPI 应用工厂。

薄壳原则(框架思维)：API 层只负责 HTTP 边界(路由、校验、序列化、错误映射)，
业务一律下沉到 service / worker / db。所有路由挂在 /api/v1 下，便于网关转发与版本演进。
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .. import __codename__, __version__
from ..db.schema import init_db
from ..env import load_local_env
from .routers import assets, geo, health, jobs, observations, reviews, tiles, tracts, uploads

API_PREFIX = "/api/v1"

def create_app() -> FastAPI:
    load_local_env()
    init_db()
    app = FastAPI(
        title=f"{__codename__} API",
        version=__version__,
        description="红树林单木智能解译平台 — 一张图服务端",
    )

    # CORS: 支持环境变量配置，默认允许本地任意端口(5173, 5174, 3000 等)及跨域访问。
    origins = os.environ.get(
        "FORESTDS_CORS_ORIGINS", "*"
    )
    origin_list = [o.strip() for o in origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origin_list if "*" not in origin_list else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    )

    # 健康探针既支持根路径直测(/healthz)，也支持挂在 /api/v1 下供代理转发。
    app.include_router(health.router)
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(uploads.router, prefix=API_PREFIX)
    app.include_router(jobs.router, prefix=API_PREFIX)
    app.include_router(tracts.router, prefix=API_PREFIX)
    app.include_router(assets.router, prefix=API_PREFIX)
    app.include_router(geo.router, prefix=API_PREFIX)
    app.include_router(tiles.router, prefix=API_PREFIX)
    app.include_router(reviews.router, prefix=API_PREFIX)
    app.include_router(observations.router, prefix=API_PREFIX)
    return app


app = create_app()
