"""单木生命周期追踪(创新点 C,核心,阶段八骨架)。

跨时相同株匹配 -> 生长轨迹/枯死状态。这是项目最具商业/科研价值的创新点。
这里先提供最近邻匹配的几何基础(纯 Python,可单测)。

TODO(阶段八): 多时相配准、匹配代价(位置+冠幅+物种)、匹配求解(匈牙利)、
生长曲线拟合、新生/枯死/砸复事件识别。
"""
from __future__ import annotations

import math

Point = tuple[float, float]


def distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def match_nearest(
    prev: list[Point],
    curr: list[Point],
    max_dist: float,
) -> list[tuple[int, int]]:
    """跨时相最近邻贪婪匹配(位置阈值 max_dist 内)。

    返回 (prev_idx, curr_idx) 配对列表;未匹配者代表新生或枯死。
    纯 Python 贪婪基线,供后续匈牙利最优匹配替换(TODO)。
    """
    pairs: list[tuple[int, int]] = []
    used_curr: set[int] = set()
    cand: list[tuple[float, int, int]] = []
    for i, p in enumerate(prev):
        for j, c in enumerate(curr):
            d = distance(p, c)
            if d <= max_dist:
                cand.append((d, i, j))
    cand.sort()
    used_prev: set[int] = set()
    for d, i, j in cand:
        if i in used_prev or j in used_curr:
            continue
        pairs.append((i, j))
        used_prev.add(i)
        used_curr.add(j)
    return pairs
