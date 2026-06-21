"""CHM 树高融合(阶段七 / 创新点 B)。

职责：
  - CHM = DSM − DEM（nodata→NaN，负值裁 0）；
  - 在检测框中心处用窗口统计量(p95/max/median/mean)估计树高；
  - RGB 与 CHM 不同分辨率/范围时，经仿射变换完成配准（RGB px → world → CHM px）；
  - 单波段栈格载入：rasterio 优先，缺失时 Pillow 降级。

依赖克制：numpy 必需；rasterio 可选(lazy)。无重依赖。全程走日志系统。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from ..geo import Affine, GeoInfo, resolve_geo
from loguru import logger as log
from ..logging_setup import log_distribution

# 树高合理上限(m)。超过视为配准/数据异常,不写入。全球最高树约 116m,红树林远低于此。
_MAX_PLAUSIBLE_HEIGHT = 120.0
_VALID_STATS = ("p95", "max", "median", "mean")


def tree_height_from_chm(dsm: float, dem: float) -> float:
    """标量树高 = DSM - DEM(负值裁 0)。纯函数,便于单测。"""
    return max(0.0, float(dsm) - float(dem))


def chm_from_dsm_dem(
    dsm,
    dem,
    *,
    dsm_nodata: Optional[float] = None,
    dem_nodata: Optional[float] = None,
    clip_negative: bool = True,
) -> np.ndarray:
    """由 DSM/DEM 阵列算 CHM。nodata→NaN,负值（可选）裁 0,返回 float32。"""
    dsm = np.asarray(dsm, dtype="float32").copy()
    dem = np.asarray(dem, dtype="float32").copy()
    if dsm.shape != dem.shape:
        raise ValueError(f"DSM/DEM 尺寸不一致: {dsm.shape} vs {dem.shape}")
    if dsm_nodata is not None:
        dsm[dsm == np.float32(dsm_nodata)] = np.nan
    if dem_nodata is not None:
        dem[dem == np.float32(dem_nodata)] = np.nan
    chm = dsm - dem
    if clip_negative:
        with np.errstate(invalid="ignore"):
            chm = np.where(np.isnan(chm), np.nan, np.maximum(chm, 0.0))
    return chm.astype("float32")


def sample_height(
    chm: np.ndarray,
    cx: float,
    cy: float,
    *,
    half_win: int = 2,
    stat: str = "p95",
) -> Optional[float]:
    """在 (cx,cy) 像素中心 ±half_win 窗口内用 stat 估计高度。

    忽略 NaN;越界或窗口全 nodata 返回 None。
    """
    if chm.ndim != 2:
        return None
    h, w = chm.shape
    col = int(round(cx))
    row = int(round(cy))
    if col < 0 or col >= w or row < 0 or row >= h:
        return None
    hw = max(0, int(half_win))
    r0, r1 = max(0, row - hw), min(h, row + hw + 1)
    c0, c1 = max(0, col - hw), min(w, col + hw + 1)
    win = chm[r0:r1, c0:c1]
    vals = win[~np.isnan(win)]
    if vals.size == 0:
        return None
    if stat == "max":
        return float(np.max(vals))
    if stat == "median":
        return float(np.median(vals))
    if stat == "mean":
        return float(np.mean(vals))
    # 默认 p95: 对冠层顶部稳健,抑制单像素噪声
    return float(np.percentile(vals, 95))


def load_single_band(path: str):
    """载入单波段栈格为 float32 阵列 + GeoInfo|None。rasterio 优先,否则 Pillow。"""
    try:
        import rasterio  # type: ignore

        with rasterio.open(path) as ds:
            arr = ds.read(1).astype("float32")
            nod = ds.nodata
            if nod is not None:
                arr = np.where(arr == np.float32(nod), np.nan, arr).astype("float32")
            geo = resolve_geo(path, transform=ds.transform, crs=ds.crs)
        log.info("[fusion] rasterio 载入单波段: {} 尺寸={}", path, (arr.shape[1], arr.shape[0]))
        return arr, geo
    except ImportError:
        pass
    except Exception as e:  # 损坏/不支持 -> 回退 Pillow
        log.warning("[fusion] rasterio 读取失败,回退 Pillow: {} ({})", path, e)
    from PIL import Image

    with Image.open(path) as im:
        arr = np.asarray(im.convert("F"), dtype="float32")
    log.warning(
        "[fusion] 未装 rasterio,Pillow 整图载入单波段: {} 尺寸={}",
        path, (arr.shape[1], arr.shape[0]),
    )
    geo = resolve_geo(path)
    return arr, geo


@dataclass
class CHMSampler:
    """在 RGB 检测框上采样 CHM 树高。支持像素对齐与仿射跨分辨率配准。"""

    chm: np.ndarray
    chm_transform: Optional[Affine] = None
    rgb_transform: Optional[Affine] = None
    stat: str = "p95"
    crown_win_px: Optional[int] = None
    max_height: float = _MAX_PLAUSIBLE_HEIGHT

    def __post_init__(self) -> None:
        if self.stat not in _VALID_STATS:
            log.warning("[fusion] 未知统计量 {},回退 p95", self.stat)
            self.stat = "p95"
        coreg = self.chm_transform is not None and self.rgb_transform is not None
        mode = "仿射配准" if coreg else "像素对齐"
        log.info(
            "CHMSampler 初始化: CHM 尺寸=%dx%d 配准模式=%s 统计量=%s",
            self.chm.shape[1], self.chm.shape[0], mode, self.stat,
        )

    @property
    def coregistered(self) -> bool:
        return self.chm_transform is not None and self.rgb_transform is not None

    def _rgb_to_chm_px(self, cx: float, cy: float) -> tuple[float, float]:
        if self.coregistered:
            wx, wy = self.rgb_transform.pixel_to_world(cx, cy)
            return self.chm_transform.world_to_pixel(wx, wy)
        return cx, cy  # 无仿射信息: 假设 1:1 像素对齐

    def _half_win_for(self, det) -> int:
        if self.crown_win_px is not None:
            return max(0, int(self.crown_win_px))
        box = max(getattr(det, "width", 0.0), getattr(det, "height", 0.0))
        hw = max(1, int(round(box * 0.25)))  # 约取冠幅四分之一
        if self.coregistered:
            ratio = self.rgb_transform.pixel_size_x() / max(self.chm_transform.pixel_size_x(), 1e-9)
            hw = max(1, int(round(hw * ratio)))
        return hw

    def height_for_detection(self, det) -> tuple[Optional[float], str]:
        cx, cy = det.center
        col, row = self._rgb_to_chm_px(cx, cy)
        v = sample_height(self.chm, col, row, half_win=self._half_win_for(det), stat=self.stat)
        if v is None:
            return None, "chm_nodata"
        if v < 0.0 or v > self.max_height:
            return None, "chm_outlier"
        return v, "chm"

    def annotate(self, detections) -> dict:
        """为每个检测写入 extra['height'] / extra['height_source'],返回统计摘要。"""
        n_h = n_nod = n_out = n_unreg = 0
        heights: list[float] = []
        for d in detections:
            h, src = self.height_for_detection(d)
            if not hasattr(d, "extra") or d.extra is None:
                continue
            d.extra["height"] = h
            d.extra["height_source"] = src
            if src == "chm":
                n_h += 1
                heights.append(h)
            elif src == "chm_nodata":
                n_nod += 1
            elif src == "chm_outlier":
                n_out += 1
            else:
                n_unreg += 1
        log.info(
            "[fusion] 树高标注: 成功={} nodata={} 超限={} 未配准={}",
            n_h, n_nod, n_out, n_unreg,
        )
        if heights:
            log_distribution(log, "树高", heights, unit="m")
        return {
            "n_with_height": n_h,
            "n_nodata": n_nod,
            "n_outlier": n_out,
            "n_unregistered": n_unreg,
        }


def build_chm_sampler(
    *,
    chm_path: Optional[str] = None,
    dsm_path: Optional[str] = None,
    dem_path: Optional[str] = None,
    rgb_transform: Optional[Affine] = None,
    stat: str = "p95",
    crown_win_px: Optional[int] = None,
) -> Optional[CHMSampler]:
    """由 --chm 或 --dsm+--dem 构造 CHMSampler。不足条件返回 None(优雅降级)。"""
    chm: Optional[np.ndarray] = None
    chm_geo: Optional[GeoInfo] = None
    if chm_path:
        chm, chm_geo = load_single_band(chm_path)
    elif dsm_path and dem_path:
        dsm, dsm_geo = load_single_band(dsm_path)
        dem, dem_geo = load_single_band(dem_path)
        if dsm.shape != dem.shape:
            log.warning("[fusion] DSM/DEM 尺寸不一致,跳过 CHM: {} vs {}", dsm.shape, dem.shape)
            return None
        chm = chm_from_dsm_dem(dsm, dem)
        chm_geo = dsm_geo or dem_geo
    else:
        return None
    finite = chm[~np.isnan(chm)]
    total = int(chm.size)
    valid = int(finite.size)
    lo = float(np.min(finite)) if finite.size else float("nan")
    hi = float(np.max(finite)) if finite.size else float("nan")
    log.info(
        "CHM 计算: 尺寸={} 有效像元={}/{} ({:.1f}%) 高程范围=[{:.2f}, {:.2f}]m",
        (chm.shape[1], chm.shape[0]), valid, total, 100.0 * valid / max(total, 1), lo, hi,
    )
    chm_transform = chm_geo.transform if chm_geo is not None else None
    return CHMSampler(
        chm=chm,
        chm_transform=chm_transform,
        rgb_transform=rgb_transform,
        stat=stat,
        crown_win_px=crown_win_px,
    )
