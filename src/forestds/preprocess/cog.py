"""COG (Cloud Optimized GeoTIFF) 检测与转换。

设计原则：
- 不依赖外部工具链（如 rio-cogeo 命令），完全基于 Python 核心生态库 rasterio 进行工业级实现。
- 支持检测“普通 TIFF（Striped）”、“Tiled TIFF（未做金字塔优化）”以及“标准 COG”。
- 支持对非 COG 进行自动重构与 Overviews 金字塔构建。
"""
from __future__ import annotations

import os
from pathlib import Path
from loguru import logger as log
from ..utils.progress import track_progress

try:
    import rasterio
    from rasterio.enums import Resampling
except ImportError:
    rasterio = None

TIFF_NORMAL = "normal"
TIFF_TILED = "tiled"
TIFF_TILED_EXTERNAL_OVERVIEW = "ext_ovr"
TIFF_COG = "COG"
TIFF_INVALID = "invalid"
TIFF_FORMAT_LABELS = {
    TIFF_NORMAL: "normal TIFF",
    TIFF_TILED: "tiled TIFF",
    TIFF_TILED_EXTERNAL_OVERVIEW: "tiled TIFF with external overview",
    TIFF_COG: "COG",
    TIFF_INVALID: "invalid",
}


def _default_cog_compress() -> str:
    try:
        from ..config import load_settings

        value = str(load_settings().get("cog.compress", "zstd") or "zstd").strip().lower()
    except Exception:
        value = "zstd"
    return value or "zstd"


def check_cog_format(image_path: str | Path) -> str:
    """检测输入影像的严格 COG 状态。

    返回下列之一:
        - "COG": 标准云优化 GeoTIFF
        - "ext_ovr": TIFF 本体分块, 金字塔在外部 .ovr
        - "tiled": 已分块但未构建金字塔的 TIFF
        - "normal": 普通未分块（Striped）的 TIFF
        - "invalid": 非 TIFF 格式或损坏文件
    """
    return inspect_tiff_format(image_path)


def inspect_tiff_format(image_path: str | Path) -> str:
    """只检查指定 tif(f) 单文件本体；外部 .ovr 不计入 COG。"""
    if rasterio is None:
        log.warning("rasterio 未安装，无法执行 COG 检测。")
        return TIFF_INVALID

    path = Path(image_path)
    if not path.exists():
        log.error(f"文件不存在: {path}")
        return TIFF_INVALID

    if path.suffix.lower() not in (".tif", ".tiff"):
        log.debug(f"非 TIFF 后缀，跳过格式检测: {path.name}")
        return TIFF_INVALID

    try:
        with rasterio.open(path) as src:
            if not src.is_tiled:
                return TIFF_NORMAL

            has_overviews = any(src.overviews(i) for i in src.indexes)
            if not has_overviews:
                return TIFF_TILED

            current = str(path.resolve())
            sidecars = [str(Path(f).resolve()) for f in src.files if str(f).lower().endswith(".ovr")]
            if any(f != current for f in sidecars):
                return TIFF_TILED_EXTERNAL_OVERVIEW
            layout = str(src.tags(ns="IMAGE_STRUCTURE").get("LAYOUT", "")).upper()
            return TIFF_COG if layout == "COG" else TIFF_TILED
    except Exception as e:
        log.error(f"打开并检测 TIFF 格式失败 {path.name}: {e}")
        return TIFF_INVALID


def inspect_tiff_error(image_path: str | Path) -> str | None:
    """Return a concise rasterio/GDAL read error for an invalid TIFF."""
    if rasterio is None:
        return "rasterio 未安装，无法读取 TIFF"
    path = Path(image_path)
    try:
        with rasterio.open(path):
            return None
    except Exception as exc:  # noqa: BLE001
        text = str(exc)
        prefix = f"{path.name}: "
        if text.startswith(prefix):
            text = text[len(prefix):]
        return text


def is_tiff_tile_ready(tiff_type: str | None) -> bool:
    """项目内瓦片服务可高效窗口读取的 TIFF 类型。"""
    return tiff_type in {TIFF_TILED_EXTERNAL_OVERVIEW, TIFF_COG}


def prepared_cog_path(
    image_path: str | Path,
    *,
    block_size: int = 512,
    compress: str | None = None,
    resampling: str = "nearest",
    min_overview_dim: int = 256,
    force: bool = False,
) -> tuple[Path, str]:
    """返回可用于瓦片服务的严格 COG 路径；必要时复用或生成同目录 *_cog.tif。"""
    path = Path(image_path).expanduser()
    compress = (compress or _default_cog_compress()).lower()
    if not path.exists() or path.suffix.lower() not in {".tif", ".tiff"}:
        return path, TIFF_INVALID

    status = inspect_tiff_format(path)
    if is_tiff_tile_ready(status):
        return path, status

    if not force:
        candidate = path if path.stem.endswith("_cog") else path.parent / f"{path.stem}_cog.tif"
        if candidate.exists():
            candidate_status = inspect_tiff_format(candidate)
            if candidate_status == TIFF_COG:
                log.info("复用已存在的严格 COG: {}", candidate)
                return candidate, TIFF_COG

    if status in {TIFF_NORMAL, TIFF_TILED}:
        out_path = _default_cog_path(path)
        log.info(
            "影像不是严格 COG，准备转换: source={} status={} target={}",
            path,
            TIFF_FORMAT_LABELS.get(status, status),
            out_path,
        )
        ok = convert_to_cog(
            path,
            out_path,
            block_size=block_size,
            compress=compress,
            resampling=resampling,
            min_overview_dim=min_overview_dim,
        )
        if ok and inspect_tiff_format(out_path) == TIFF_COG:
            return out_path, TIFF_COG
    return path, status


def _default_cog_path(path: Path) -> Path:
    if path.stem.endswith("_cog"):
        return path.parent / f"{path.stem}_strict.tif"
    return path.parent / f"{path.stem}_cog.tif"


def convert_to_cog(
    in_path: str | Path,
    out_path: str | Path,
    block_size: int = 512,
    compress: str | None = None,
    resampling: str = "nearest",
    min_overview_dim: int = 256,
) -> bool:
    """使用 rasterio 将普通 TIFF 或 Tiled TIFF 转换为标准 COG。"""
    if rasterio is None:
        log.error("rasterio 未安装，无法执行 COG 转换。")
        return False

    compress = (compress or _default_cog_compress()).lower()
    in_p = Path(in_path)
    out_p = Path(out_path)
    if not in_p.exists():
        log.error("转换源文件不存在: {}", in_p)
        return False

    log.info("开始将 {} 转换为 COG 格式...", in_p.name)
    if _convert_with_cog_driver(
        in_p,
        out_p,
        block_size=block_size,
        compress=compress,
        resampling=resampling,
    ):
        return True

    log.warning("GDAL COG driver 转换失败，回退到 rasterio 手写转换路径: {}", in_p)
    try:
        with rasterio.Env(GDAL_NUM_THREADS="ALL_CPUS", NUM_THREADS="ALL_CPUS"):
            with rasterio.open(in_p) as src:
                profile = src.profile.copy()
                profile.update(
                    driver="GTiff",
                    tiled=True,
                    blockxsize=block_size,
                    blockysize=block_size,
                    compress=compress.lower(),
                    interleave="pixel",
                    BIGTIFF="IF_SAFER",
                )
                if src.nodata is not None:
                    profile["nodata"] = src.nodata

                out_p.parent.mkdir(parents=True, exist_ok=True)
                with rasterio.open(out_p, "w", **profile) as dst:
                    all_tasks = [
                        (i, window)
                        for i in range(1, src.count + 1)
                        for _, window in src.block_windows(i)
                    ]
                    for i, window in track_progress(all_tasks, desc="转换 COG 进度"):
                        dst.write(src.read(i, window=window), indexes=i, window=window)

        overview_env = {
            "COMPRESS_OVERVIEW": compress.upper(),
            "INTERLEAVE_OVERVIEW": "PIXEL",
            "GDAL_TIFF_OVR_BLOCKSIZE": str(block_size),
            "BIGTIFF_OVERVIEW": "IF_SAFER",
        }
        with rasterio.Env(GDAL_NUM_THREADS="ALL_CPUS", NUM_THREADS="ALL_CPUS", **overview_env):
            with rasterio.open(out_p, "r+") as dst:
                factors: list[int] = []
                factor = 2
                while min(dst.width // factor, dst.height // factor) >= min_overview_dim:
                    factors.append(factor)
                    factor *= 2
                if factors:
                    resampling_map = {
                        "nearest": Resampling.nearest,
                        "bilinear": Resampling.bilinear,
                        "cubic": Resampling.cubic,
                        "average": Resampling.average,
                    }
                    algo = resampling_map.get(resampling.lower(), Resampling.nearest)
                    log.debug("构建金字塔 Overviews 层级因子: {}", factors)
                    dst.build_overviews(factors, algo)
                    dst.update_tags(ns="rio_overview", resampling=resampling.lower())

        log.info("COG 转换完成: {}", out_p.name)
        return True
    except Exception as exc:  # noqa: BLE001
        log.opt(exception=False).error("转换 COG 失败: {} — {}", type(exc).__name__, exc)
        if out_p.exists():
            try:
                os.remove(out_p)
            except Exception:
                pass
        return False


def _convert_with_cog_driver(
    in_p: Path,
    out_p: Path,
    *,
    block_size: int,
    compress: str,
    resampling: str,
) -> bool:
    try:
        from rasterio.shutil import copy as rio_copy

        out_p.parent.mkdir(parents=True, exist_ok=True)
        if out_p.exists():
            out_p.unlink()
        log.info(
            "使用 GDAL COG driver 转换: source={} target={} block={} compress={} resampling={}",
            in_p,
            out_p,
            block_size,
            compress.upper(),
            resampling.upper(),
        )
        rio_copy(
            str(in_p),
            str(out_p),
            driver="COG",
            COMPRESS=compress.upper(),
            BLOCKSIZE=block_size,
            OVERVIEWS="AUTO",
            RESAMPLING=resampling.upper(),
            BIGTIFF="IF_SAFER",
            NUM_THREADS="ALL_CPUS",
        )
        if inspect_tiff_format(out_p) == TIFF_COG:
            log.info("COG 转换完成: {}", out_p.name)
            return True
        log.warning("COG driver 输出未通过严格 COG 检测: {}", out_p)
    except Exception as exc:  # noqa: BLE001
        log.warning("COG driver 转换异常: {} - {}", type(exc).__name__, exc)
    if out_p.exists():
        try:
            out_p.unlink()
        except Exception:
            pass
    return False
