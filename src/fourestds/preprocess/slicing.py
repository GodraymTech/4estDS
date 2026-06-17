"""创新点 A:最优多尺度规则切片。

该模块是项目的数学核心。它回答一个问题:面对一幅超大 GeoTIFF 与一个
固定输入尺寸的检测器,**怎样选择切片边长 T 与重叠 o**,才能在"目标不被
过度缩小而丢失检测力"与"跨缝目标不被截断"之间取得最优权衡。

流水线(理论)::

  1) GSD 归一     : 把物理冠幅(米)换算为原始像素尺寸,去除分辨率差异。
  2) 特征尺度     : Lindeberg 归一化 LoG 自动尺度选择(可选,需 numpy),
                    用于从影像估计冠幅分布(廉价预扫)。
  3) 离散尺度集   : 在 log 尺寸上对冠幅分布做 1D 聚类(k-means),得到 K 个代表尺度。
  4) 最优参数     : 对每个尺度档,求解受约束的 (T*, o*),使算力代价最小且
                    满足可检测性(T<=T_max)与完整性(o>=大冠幅分位)。
  5) 四叉树分层   : 若区域内目标尺寸差异大,按规则 2x2 递归细分,每区只切一次。
  6) nodata 跳过   : 用积分图 O(1) 查询区域有效像素占比,全 nodata 区域直接跳过。

本文件的 4、5、6 与截断概率均为**纯 Python 实现**(无重依赖,可单测);
第 2 步的 LoG 特征尺度需 numpy,作为可选增强放在 ``characteristic_scale``。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# 1) GSD 归一
# --------------------------------------------------------------------------- #


def crown_px_size(crown_m: float, gsd_m_per_px: float) -> float:
    """物理冠幅(米) -> 原始影像像素尺寸。gsd 单位: 米/像素。"""
    if gsd_m_per_px <= 0:
        raise ValueError("gsd_m_per_px must be > 0")
    return crown_m / gsd_m_per_px


# --------------------------------------------------------------------------- #
# 4) 截断概率与最优参数
# --------------------------------------------------------------------------- #


def truncation_probability(w: float, tile: float, overlap: float) -> float:
    """单个目标(宽 w 像素)被规则网格切片截断的概率。

    设网格步进 s = tile - overlap(有效步长),目标中心在一个周期内均匀分布。
    只要某张切片能完整包含目标则不算截断(重叠区保证跨缝目标仍可被某块完整看到)。
    当有效步长 s >= w 时,存在不截断的放置;截断概率为 max(0, (w - overlap) / tile)
    当 s < w (即 overlap < w 且 tile 偏小) 时迅速上升;w >= tile 时恒为 1。
    """
    if tile <= 0:
        raise ValueError("tile must be > 0")
    if w >= tile:
        return 1.0
    p = (w - overlap) / tile
    if p < 0:
        return 0.0
    return min(1.0, p)


def expected_truncation(sizes: list[float], tile: float, overlap: float) -> float:
    """给定冠幅像素尺寸样本,返回平均截断概率。"""
    if not sizes:
        return 0.0
    return sum(truncation_probability(w, tile, overlap) for w in sizes) / len(sizes)


@dataclass
class TileParams:
    tile: int          # 切片边长(原始像素)
    overlap: int       # 重叠(原始像素)
    scale_px: float    # 该档代表冠幅像素尺寸
    exp_trunc: float   # 期望截断概率
    cost: float        # 目标函数值


def optimize_tile_params(
    scale_px: float,
    model_input: int,
    d_min_px: float,
    w_large_px: float,
    epsilon: float = 0.05,
    lambda_cost: float = 0.15,
    tile_grid: tuple[int, ...] = (512, 640, 768, 896, 1024, 1280, 1536, 2048),
    overlap_ratios: tuple[float, ...] = (0.1, 0.15, 0.2, 0.25, 0.3),
) -> TileParams:
    """为某一尺度档求解最优 (T*, o*)。

    约束::
      (可检测性) 目标缩放到模型输入后不小于 d_min_px:
          scale_px * (model_input / T) >= d_min_px  =>  T <= model_input * scale_px / d_min_px
      (完整性) 期望截断概率不超 epsilon(用大冠幅 w_large 作为最坏情形):
          truncation_probability(w_large, T, o) <= epsilon

    目标(最小化)::
      cost = 算力代价(∝ 切片数 ∝ 1/(T-o)^2) + lambda * 期望截断

    返回满足约束且 cost 最小的参数;若无可行解则放宽到最接近可检测上限。
    """
    if scale_px <= 0 or model_input <= 0 or d_min_px <= 0:
        raise ValueError("scale_px, model_input, d_min_px must be > 0")

    t_max = model_input * scale_px / d_min_px  # 可检测性上限
    best: TileParams | None = None
    relaxed_best: TileParams | None = None

    for tile in tile_grid:
        detectable = tile <= t_max
        for r in overlap_ratios:
            overlap = int(round(tile * r))
            step = tile - overlap
            if step <= 0:
                continue
            trunc = truncation_probability(w_large_px, tile, overlap)
            # 算力代价∝切片数密度 ∝ 1/step^2(归一化到 model_input)
            density = (model_input / step) ** 2
            cost = density + lambda_cost * trunc
            cand = TileParams(
                tile=tile, overlap=overlap, scale_px=scale_px,
                exp_trunc=trunc, cost=cost,
            )
            # 记录放宽解(仅要求可检测)
            if detectable and (relaxed_best is None or cand.cost < relaxed_best.cost):
                relaxed_best = cand
            # 严格解(同时满足完整性)
            if detectable and trunc <= epsilon:
                if best is None or cand.cost < best.cost:
                    best = cand

    if best is not None:
        return best
    if relaxed_best is not None:
        return relaxed_best
    # 连可检测性都无法满足(目标太大):选最小切片作为兜底
    tile = min(tile_grid)
    overlap = int(round(tile * overlap_ratios[len(overlap_ratios) // 2]))
    trunc = truncation_probability(w_large_px, tile, overlap)
    return TileParams(tile, overlap, scale_px, trunc, float("inf"))


# --------------------------------------------------------------------------- #
# 3) 尺度聚类(log 域 1D k-means)
# --------------------------------------------------------------------------- #


def cluster_scales(sizes: list[float], k: int = 3, iters: int = 50) -> list[float]:
    """在 log 尺度上对冠幅尺寸做 1D k-means,返回按升序排列的代表尺度(原域)。

    纯 Python 实现,不依赖 numpy/sklearn。空输入返回空列表。
    """
    pts = [math.log(s) for s in sizes if s > 0]
    if not pts:
        return []
    k = max(1, min(k, len(set(pts))))
    pts_sorted = sorted(pts)
    # 按分位初始化质心
    centers = [pts_sorted[int((i + 0.5) / k * len(pts_sorted))] for i in range(k)]
    for _ in range(iters):
        buckets: list[list[float]] = [[] for _ in range(k)]
        for x in pts:
            j = min(range(k), key=lambda c: abs(x - centers[c]))
            buckets[j].append(x)
        new_centers = []
        for j in range(k):
            if buckets[j]:
                new_centers.append(sum(buckets[j]) / len(buckets[j]))
            else:
                new_centers.append(centers[j])
        if max(abs(a - b) for a, b in zip(new_centers, centers)) < 1e-9:
            centers = new_centers
            break
        centers = new_centers
    return sorted(math.exp(c) for c in centers)


# --------------------------------------------------------------------------- #
# 6) nodata 积分图(summed-area table)
# --------------------------------------------------------------------------- #


def integral_image(mask: list[list[int]]) -> list[list[int]]:
    """构建 (H+1)x(W+1) 积分图。mask[y][x]=1 表示有效像素。"""
    h = len(mask)
    w = len(mask[0]) if h else 0
    ii = [[0] * (w + 1) for _ in range(h + 1)]
    for y in range(h):
        row_sum = 0
        for x in range(w):
            row_sum += mask[y][x]
            ii[y + 1][x + 1] = ii[y][x + 1] + row_sum
    return ii


def region_sum(ii: list[list[int]], x: int, y: int, w: int, h: int) -> int:
    """O(1) 查询矩形区域 [x, x+w) x [y, y+h) 的有效像素个数(四角法)。"""
    x2, y2 = x + w, y + h
    return ii[y2][x2] - ii[y][x2] - ii[y2][x] + ii[y][x]


def is_all_nodata(ii: list[list[int]], x: int, y: int, w: int, h: int) -> bool:
    """区域内有效像素为 0 则全 nodata,可直接跳过。"""
    return region_sum(ii, x, y, w, h) == 0


# --------------------------------------------------------------------------- #
# 5) 规则四叉树分层
# --------------------------------------------------------------------------- #


@dataclass
class Tile:
    x: int
    y: int
    size: int
    level: int


def build_quadtree(
    width: int,
    height: int,
    target_size_fn,
    root_size: int,
    min_size: int,
    max_level: int = 6,
    tol: float = 1.3,
) -> list[Tile]:
    """规则四叉树切片。

    从 root_size 出发,对每个区域查询其"裁判"给出的本地目标尺寸 target_size_fn(cx, cy)。
    若当前块尺寸明显大于局部目标(block > target * tol) 且未到最细层/最小块,则拆为 2x2;
    否则该区只切一次(输出一个 tile)。单一尺度时退化为均匀网格。

    target_size_fn: (center_x:int, center_y:int) -> float  返回该处期望切片边长(像素)。
    """
    tiles: list[Tile] = []

    def recurse(x: int, y: int, size: int, level: int) -> None:
        # 裁剪到影像边界内才计算中心
        if x >= width or y >= height:
            return
        cx = min(x + size // 2, width - 1)
        cy = min(y + size // 2, height - 1)
        target = target_size_fn(cx, cy)
        can_split = (
            level < max_level
            and size // 2 >= min_size
            and target > 0
            and size > target * tol
        )
        if can_split:
            half = size // 2
            for dy in (0, half):
                for dx in (0, half):
                    recurse(x + dx, y + dy, half, level + 1)
        else:
            tiles.append(Tile(x=x, y=y, size=size, level=level))

    # 以 root_size 铺满全图
    step = root_size
    y = 0
    while y < height:
        x = 0
        while x < width:
            recurse(x, y, step, 0)
            x += step
        y += step
    return tiles


# --------------------------------------------------------------------------- #
# 2) Lindeberg 特征尺度(可选增强,需 numpy)
# --------------------------------------------------------------------------- #


def characteristic_scale(gray, sigmas=None):  # pragma: no cover - 需 numpy
    """Lindeberg 归一化 LoG 自动尺度选择(召回最强响应对应的 sigma)。

    需要 numpy。返回 (best_sigma, response_per_sigma)。该函数为可选增强,不参与核心单测。
    """
    import numpy as np

    if sigmas is None:
        sigmas = [2 ** (i / 2) for i in range(2, 12)]
    g = np.asarray(gray, dtype=float)

    def gaussian_blur(arr, sigma):
        radius = max(1, int(3 * sigma))
        xs = np.arange(-radius, radius + 1)
        kern = np.exp(-(xs ** 2) / (2 * sigma * sigma))
        kern /= kern.sum()
        tmp = np.apply_along_axis(lambda m: np.convolve(m, kern, mode="same"), 0, arr)
        return np.apply_along_axis(lambda m: np.convolve(m, kern, mode="same"), 1, tmp)

    responses = []
    for s in sigmas:
        blurred = gaussian_blur(g, s)
        lap = (
            -4 * blurred
            + np.roll(blurred, 1, 0)
            + np.roll(blurred, -1, 0)
            + np.roll(blurred, 1, 1)
            + np.roll(blurred, -1, 1)
        )
        # 尺度归一化: sigma^2 * |LoG|
        responses.append(float((s * s * np.abs(lap)).mean()))
    best_idx = max(range(len(sigmas)), key=lambda i: responses[i])
    return sigmas[best_idx], responses


# --------------------------------------------------------------------------- #
# CLI 演示入口(无真实影像时用合成样本展示最优化)
# --------------------------------------------------------------------------- #


def plan_tiles_demo(settings) -> dict:
    """用配置中的参数跑一次最优化演示(无需真实 GeoTIFF),返回摘要。"""
    gsd = settings.get("detect.model_input", 1024) and settings.get("slicing", {})
    sl = settings.section("slicing")
    det = settings.section("detect")
    expected_crown_m = float(sl.get("expected_crown_m", 4.0))
    model_input = int(det.get("model_input", 1024))
    d_min = float(sl.get("d_min_px", 24))
    epsilon = float(sl.get("epsilon", 0.05))
    lam = float(sl.get("lambda_cost", 0.15))
    # 假设 GSD 0.1 m/px,合成一组冠幅(米)样本
    gsd_val = 0.1
    crowns_m = [2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
    sizes_px = [crown_px_size(c, gsd_val) for c in crowns_m]
    scales = cluster_scales(sizes_px, k=int(sl.get("max_scales", 3)))
    w_large = max(sizes_px)
    plans = [
        optimize_tile_params(
            scale_px=s, model_input=model_input, d_min_px=d_min,
            w_large_px=w_large, epsilon=epsilon, lambda_cost=lam,
        )
        for s in scales
    ]
    return {
        "gsd_m_per_px": gsd_val,
        "expected_crown_m": expected_crown_m,
        "scales_px": [round(s, 1) for s in scales],
        "plans": [
            {"scale_px": round(p.scale_px, 1), "tile": p.tile,
             "overlap": p.overlap, "exp_trunc": round(p.exp_trunc, 4)}
            for p in plans
        ],
    }
