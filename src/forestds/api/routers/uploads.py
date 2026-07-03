"""影像上传端点。

- POST /uploads -> 保存上传影像到存储后端，返回 key/filename/size。

薄壳原则(框架思维)：仅做 HTTP 边界(接收 multipart、生成 key、落存储)，
key 回传给 /jobs/infer 发起推理。存储经 Storage 抽象(local|s3)，本路由与具体后端解耦。
"""
from __future__ import annotations

import os
import re
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from ..deps import get_storage_dep
from ..schemas import UploadResponse

router = APIRouter(prefix="/uploads", tags=["uploads"])

# 允许的影像扩展名(遥感正射影像/瓦片)。其余一律拒绝，避免误传非影像。
_ALLOWED_EXT = {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".img"}
# 单文件上限(GB)。大图窗口化推理，默认 4GB，可用环境变量放宽。
_MAX_BYTES = int(float(os.environ.get("forestds_UPLOAD_MAX_GB", "4")) * 1024**3)

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_name(filename: str) -> str:
    """取文件名基名并清洗不安全字符(防止路径穿越/非法字符)。"""
    base = os.path.basename(filename).strip()
    base = _SAFE_RE.sub("_", base)
    return base or "image"


@router.post("", response_model=UploadResponse, summary="上传影像")
def upload_image(
    file: UploadFile = File(..., description="遥感影像(GeoTIFF 等)"),
    storage=Depends(get_storage_dep),
) -> UploadResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")

    safe = _safe_name(file.filename)
    ext = os.path.splitext(safe)[1].lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(
            status_code=415,
            detail=f"不支持的影像格式: {ext or '未知'}(允许: {', '.join(sorted(_ALLOWED_EXT))})",
        )

    # 以底层文件测量大小并做上限校验，随后回绕到起始供存储写入。
    stream = file.file
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    if size == 0:
        raise HTTPException(status_code=400, detail="空文件")
    if size > _MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大: {size} 字节，超过上限 {_MAX_BYTES} 字节",
        )

    # key 语义: uploads/YYYY/MM/<随机短码>_<安全文件名>，与具体存储后端无关。
    now = datetime.now(timezone.utc)
    key = f"uploads/{now:%Y/%m}/{secrets.token_hex(4)}_{safe}"
    storage.save_stream(key, stream)
    return UploadResponse(key=key, filename=safe, size=size)
