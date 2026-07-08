"""推理输入路径规范化与元数据检查。

API 层接收的是用户输入的本机路径字符串；推理层需要的是 Worker 可读的
WSL/Linux 本地路径。这里集中处理路径清洗、Windows 路径转换、影像发现与
轻量元数据读取，避免路由和前端各自猜测。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from PIL import Image

VALID_IMAGE_SUFFIXES: frozenset[str] = frozenset(
    {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".img"}
)

_WINDOWS_DRIVE_RE = re.compile(r"^([A-Za-z]):[\\/](.*)$")
_QUOTE_PAIRS = {
    '"': '"',
    "'": "'",
    "“": "”",
    "‘": "’",
}
_DATE_TAG_KEYS = (
    "TIFFTAG_DATETIME",
    "DateTime",
    "datetime",
    "ACQUISITION_DATE",
    "AcquisitionDate",
    "DATE_ACQUIRED",
    "date",
)


@dataclass(frozen=True)
class ImageMetadata:
    path: str
    stem: str
    width: int | None = None
    height: int | None = None
    crs_epsg: int | None = None
    crs_wkt: str | None = None
    phase_id: str | None = None
    phase_source: str | None = None


def normalize_user_path(raw: str) -> str:
    """把用户输入路径规范化为后端可尝试访问的路径字符串。

    - 去掉首尾空白与成对引号；
    - 支持 ``file://`` 前缀；
    - 把 ``C:\\Users\\a\\x.tif`` 转为 ``/mnt/c/Users/a/x.tif``。
    """
    value = (raw or "").strip()
    if value.startswith("file://"):
        value = value[7:]
    if len(value) >= 2 and value[0] in _QUOTE_PAIRS and value[-1] == _QUOTE_PAIRS[value[0]]:
        value = value[1:-1].strip()

    match = _WINDOWS_DRIVE_RE.match(value)
    if match:
        drive, rest = match.groups()
        rest = rest.replace("\\", "/")
        return f"/mnt/{drive.lower()}/{rest}"
    return value.replace("\\", "/")


def resolve_user_path(raw: str) -> Path:
    """解析并校验用户路径存在。"""
    normalized = normalize_user_path(raw)
    if not normalized:
        raise ValueError("输入路径不能为空")
    path = Path(normalized).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"输入路径不存在: {normalized}")
    return path.resolve()


def resolve_optional_user_path(raw: str | None) -> str | None:
    """解析可选辅助数据路径；空值返回 None。"""
    if raw is None or not str(raw).strip():
        return None
    return str(resolve_user_path(raw))


def is_supported_image(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VALID_IMAGE_SUFFIXES


def resolve_images_from_path(path: Path) -> list[Path]:
    """按当前批量推理语义发现影像：文件直用，目录仅扫描一级文件。"""
    if path.is_file():
        return [path] if is_supported_image(path) else []
    if path.is_dir():
        return sorted(p.resolve() for p in path.iterdir() if is_supported_image(p))
    return []


def extract_image_phase_id(path: str | Path) -> tuple[str | None, str | None]:
    """从影像元数据提取 YYYYMMDD 日期。

    优先读取 GeoTIFF/raster tags，其次读取普通图片 EXIF，最后沿用历史行为回退到
    文件修改日期，保证旧 CLI/API 的默认日期语义不突然失效。
    """
    p = Path(path)
    tag_date = _extract_raster_date(p)
    if tag_date:
        return tag_date, "raster_tags"

    exif_date = _extract_pil_date(p)
    if exif_date:
        return exif_date, "image_exif"

    try:
        return datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y%m%d"), "file_mtime"
    except OSError:
        return None, None


def inspect_image(path: str | Path) -> ImageMetadata:
    """读取单幅影像的轻量元数据，不加载整图像素。"""
    p = Path(path).resolve()
    width: int | None = None
    height: int | None = None
    crs_epsg: int | None = None
    crs_wkt: str | None = None

    if p.suffix.lower() in (".tif", ".tiff", ".img"):
        try:
            import rasterio

            with rasterio.open(p) as src:
                width = int(src.width)
                height = int(src.height)
                if src.crs:
                    crs_epsg = src.crs.to_epsg()
                    crs_wkt = src.crs.to_wkt()
        except Exception:
            # 元数据预读失败不阻断提交；真正推理阶段会给出完整错误。
            pass

    if width is None or height is None:
        try:
            with Image.open(p) as img:
                width, height = img.size
        except Exception:
            pass

    phase_id, source = extract_image_phase_id(p)
    return ImageMetadata(
        path=str(p),
        stem=p.stem,
        width=width,
        height=height,
        crs_epsg=crs_epsg,
        crs_wkt=crs_wkt,
        phase_id=phase_id,
        phase_source=source,
    )


def inspect_input_path(raw: str) -> tuple[Literal["file", "directory"], Path, list[ImageMetadata]]:
    """检查用户输入，返回输入类型、规范路径和影像元数据列表。"""
    path = resolve_user_path(raw)
    images = resolve_images_from_path(path)
    if not images:
        allowed = ", ".join(sorted(VALID_IMAGE_SUFFIXES))
        raise ValueError(f"未找到可推理影像文件，支持格式: {allowed}")
    kind: Literal["file", "directory"] = "directory" if path.is_dir() else "file"
    return kind, path, [inspect_image(p) for p in images]


def _extract_raster_date(path: Path) -> str | None:
    if path.suffix.lower() not in (".tif", ".tiff", ".img"):
        return None
    try:
        import rasterio

        with rasterio.open(path) as src:
            tags = src.tags()
    except Exception:
        return None
    for key in _DATE_TAG_KEYS:
        date = _digits_to_yyyymmdd(tags.get(key))
        if date:
            return date
    return None


def _extract_pil_date(path: Path) -> str | None:
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            candidates = [
                exif.get(36867),  # DateTimeOriginal
                exif.get(36868),  # DateTimeDigitized
                exif.get(306),  # DateTime
            ]
    except Exception:
        return None
    for candidate in candidates:
        date = _digits_to_yyyymmdd(candidate)
        if date:
            return date
    return None


def _digits_to_yyyymmdd(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 8:
        return None
    yyyymmdd = digits[:8]
    try:
        datetime.strptime(yyyymmdd, "%Y%m%d")
    except ValueError:
        return None
    return yyyymmdd
