"""FastAPI 应用工厂。

薄壳原则(框架思维)：API 层只负责 HTTP 边界(路由、校验、序列化、错误映射)，
业务一律下沉到 service / worker / db。所有路由挂在 /api/v1 下，便于网关转发与版本演进。
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

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

    # GZip: 自动压缩大于 1KB 的纯文本/JSON，针对几万条检测框要素的 GeoJSON 压缩率可达 80% 以上
    app.add_middleware(GZipMiddleware, minimum_size=1024)

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

    # 静态前端 SPA 托管 (制品发布生产模式)
    static_dir = os.environ.get("FORESTDS_STATIC_DIR")
    if not static_dir:
        candidate = os.path.join(os.getcwd(), "dist")
        if os.path.isdir(candidate):
            static_dir = candidate

    if static_dir and os.path.isdir(static_dir):
        from fastapi.staticfiles import StaticFiles
        from starlette.responses import FileResponse

        assets_dir = os.path.join(static_dir, "assets")
        if os.path.isdir(assets_dir):
            app.mount("/assets", StaticFiles(directory=assets_dir), name="static_assets")

        index_file = os.path.join(static_dir, "index.html")

        @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
        async def serve_spa(full_path: str):
            if full_path.startswith("api/") or full_path.startswith("healthz") or full_path.startswith("health"):
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="Not Found")
            file_path = os.path.join(static_dir, full_path)
            if full_path and os.path.isfile(file_path):
                return FileResponse(file_path)
            if os.path.isfile(index_file):
                return FileResponse(index_file)
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Frontend index.html not found")

    return app


app = create_app()

