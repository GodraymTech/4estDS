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


def check_cog_format(image_path: str | Path) -> str:
    """检测输入影像的 COG 格式状态。
    
    返回下列之一:
        - "cog": 标准云优化 GeoTIFF
        - "tiled_tiff": 已分块但未构建金字塔的 TIFF
        - "normal_tiff": 普通未分块（Striped）的 TIFF
        - "invalid": 非 TIFF 格式或损坏文件
    """
    if rasterio is None:
        log.warning("rasterio 未安装，无法执行 COG 检测。")
        return "invalid"

    path = Path(image_path)
    if not path.exists():
        log.error(f"文件不存在: {path}")
        return "invalid"

    if path.suffix.lower() not in (".tif", ".tiff"):
        log.debug(f"非 TIFF 后缀，跳过格式检测: {path.name}")
        return "invalid"

    # 优先检测同目录下是否已存在带 _cog 后缀的同名优化文件
    if not path.stem.endswith("_cog"):
        cog_path = path.parent / f"{path.stem}_cog{path.suffix}"
        if cog_path.exists():
            log.info(f"检测到同目录下存在 {cog_path.name}，优先对其进行 COG 格式检测。")
            path = cog_path

    try:
        with rasterio.open(path) as src:
            if not src.is_tiled:
                return "normal_tiff"
            
            # 检查是否有金字塔过载层 (overviews)
            has_overviews = False
            for i in src.indexes:
                if len(src.overviews(i)) > 0:
                    has_overviews = True
                    break
            
            if has_overviews:
                return "cog"
            else:
                return "tiled_tiff"
    except Exception as e:
        log.error(f"打开并检测 TIFF 格式失败 {path.name}: {e}")
        return "invalid"


def convert_to_cog(
    in_path: str | Path,
    out_path: str | Path,
    block_size: int = 512,
    compress: str = "deflate",
    resampling: str = "nearest",
    min_overview_dim: int = 256,
) -> bool:
    """使用 rasterio 将普通 TIFF 或 Tiled TIFF 转换为标准 COG。
    
    返回是否成功转换。
    """
    if rasterio is None:
        log.error("rasterio 未安装，无法执行 COG 转换。")
        return False

    in_p = Path(in_path)
    out_p = Path(out_path)

    if not in_p.exists():
        log.error(f"转换源文件不存在: {in_p}")
        return False

    log.info(f"开始将 {in_p.name} 转换为 COG 格式...")
    try:
        # 1. 拷贝元数据并写入分块 Tiled 影像
        with rasterio.open(in_p) as src:
            profile = src.profile.copy()
            # 注入 COG 最佳实践选项
            profile.update(
                driver="GTiff",
                tiled=True,
                blockxsize=block_size,
                blockysize=block_size,
                compress=compress.lower(),
                interleave="pixel"
            )
            
            # 如果源文件有 nodata 属性，确保带上
            if src.nodata is not None:
                profile["nodata"] = src.nodata

            # 写入目标文件数据
            out_p.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.open(out_p, "w", **profile) as dst:
                all_tasks = []
                for i in range(1, src.count + 1):
                    for _, window in src.block_windows(i):
                        all_tasks.append((i, window))
                
                for i, window in track_progress(all_tasks, desc="转换 COG 进度"):
                    data = src.read(i, window=window)
                    dst.write(data, indexes=i, window=window)
                    
        # 2. 以读写模式重新打开，构建多层金字塔 Overviews
        with rasterio.open(out_p, "r+") as dst:
            w, h = dst.width, dst.height
            factors = []
            f = 2
            # 持续下采样直到最小维度的分辨率在 min_overview_dim 左右即可停止
            while min(w // f, h // f) >= min_overview_dim:
                factors.append(f)
                f *= 2
            
            if factors:
                log.debug(f"构建金字塔 Overviews 层级因子: {factors}")
                resampling_map = {
                    "nearest": Resampling.nearest,
                    "bilinear": Resampling.bilinear,
                    "cubic": Resampling.cubic,
                    "average": Resampling.average,
                }
                algo = resampling_map.get(resampling.lower(), Resampling.nearest)
                dst.build_overviews(factors, algo)
                # 记录重采样标签
                dst.update_tags(ns="rio_overview", resampling=resampling.lower())
        
        log.info(f"COG 转换完成: {out_p.name}")
        return True
    except Exception as e:
        log.opt(exception=False).error(f"转换 COG 失败: {type(e).__name__} — {e}")
        if out_p.exists():
            try:
                os.remove(out_p)
            except Exception:
                pass
        return False
