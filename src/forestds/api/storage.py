"""对象存储抽象 (Strategy Pattern)。

为什么存在：API 接收上传影像、Worker 读取影像、报告/导出件回写，都需要一个
统一的存储接口。通过 Storage 协议解耦上层与具体后端(SOLID: 依赖倒置)。

v1.0 默认 LocalStorage(共享卷)，零外部依赖、开箱即用；
生产切 S3Storage(MinIO)，仅需配置不改上层代码(开闭原则)。

key 语义：形如 ``uploads/2026/07/ab12_forest.tif`` 的相对键，与后端无关。
两个后端都能给 Worker 返回一个可读的本地路径(local 直接映射; s3 下载到缓存)。
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import BinaryIO, Protocol, runtime_checkable

from loguru import logger as log


@runtime_checkable
class Storage(Protocol):
    """存储后端统一接口。"""

    def save_stream(self, key: str, stream: BinaryIO) -> str:
        """写入一个字节流到 key，返回 key。"""
        ...

    def local_path(self, key: str) -> str:
        """返回一个 Worker 可读的本地绝对路径(必要时下载到缓存)。"""
        ...

    def exists(self, key: str) -> bool:
        ...


class LocalStorage:
    """本地共享卷存储。API 与 Worker 挂载同一个 ``root`` 目录。"""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _abs(self, key: str) -> Path:
        # 防止路径穿越：规范化后必须仍在 root 内。
        p = (self.root / key).resolve()
        if not str(p).startswith(str(self.root)):
            raise ValueError(f"非法存储 key(路径穿越): {key!r}")
        return p

    def save_stream(self, key: str, stream: BinaryIO) -> str:
        dst = self._abs(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(dst, "wb") as f:
            shutil.copyfileobj(stream, f)
        log.info("LocalStorage 写入: key={} -> {}", key, dst)
        return key

    def local_path(self, key: str) -> str:
        p = self._abs(key)
        if not p.exists():
            raise FileNotFoundError(f"存储对象不存在: {key}")
        return str(p)

    def exists(self, key: str) -> bool:
        return self._abs(key).exists()


class S3Storage:
    """MinIO / S3 兼容存储。用于生产环境。

    延迟导入 ``minio`` SDK，避免未安装时影响 LocalStorage 路径。
    下载到本地缓存目录供 Worker 读取(引擎使用 rasterio 窗口读，需本地文件)。
    """

    def __init__(self, *, endpoint: str, access_key: str, secret_key: str,
                 bucket: str, secure: bool = False, cache_dir: str | Path | None = None):
        from minio import Minio  # 延迟导入

        self._client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self.bucket = bucket
        self.cache_dir = Path(cache_dir).expanduser().resolve() if cache_dir else Path("/tmp/forestds_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if not self._client.bucket_exists(bucket):
            self._client.make_bucket(bucket)

    def save_stream(self, key: str, stream: BinaryIO) -> str:
        # -1 长度 + part_size 让 minio 分块上传未知大小的流。
        self._client.put_object(self.bucket, key, stream, length=-1, part_size=10 * 1024 * 1024)
        log.info("S3Storage 写入: bucket={} key={}", self.bucket, key)
        return key

    def local_path(self, key: str) -> str:
        dst = self.cache_dir / key
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            self._client.fget_object(self.bucket, key, str(dst))
        return str(dst)

    def exists(self, key: str) -> bool:
        from minio.error import S3Error

        try:
            self._client.stat_object(self.bucket, key)
            return True
        except S3Error:
            return False


_storage_singleton: Storage | None = None


def get_storage(settings=None) -> Storage:
    """根据配置/环境变量构造存储后端(单例)。

    选择: env ``forestds_STORAGE_BACKEND`` (local|s3) > config ``storage.backend`` > local。
    """
    global _storage_singleton
    if _storage_singleton is not None:
        return _storage_singleton

    from .. import paths

    backend = os.environ.get("forestds_STORAGE_BACKEND")
    if not backend and settings is not None:
        backend = settings.get("storage.backend")
    backend = (backend or "local").lower()

    if backend == "s3":
        _storage_singleton = S3Storage(
            endpoint=os.environ.get("forestds_S3_ENDPOINT", "localhost:9000"),
            access_key=os.environ.get("forestds_S3_ACCESS_KEY", "minioadmin"),
            secret_key=os.environ.get("forestds_S3_SECRET_KEY", "minioadmin"),
            bucket=os.environ.get("forestds_S3_BUCKET", "forestds"),
            secure=os.environ.get("forestds_S3_SECURE", "false").lower() == "true",
            cache_dir=os.environ.get("forestds_S3_CACHE_DIR"),
        )
    else:
        root = os.environ.get("forestds_STORAGE_ROOT") or str(paths.home_dir() / "storage")
        _storage_singleton = LocalStorage(root)
    log.info("存储后端就绪: backend={}", backend)
    return _storage_singleton
