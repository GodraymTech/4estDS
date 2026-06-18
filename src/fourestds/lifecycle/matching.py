"""跨时相单木匹配(阶段八 / 创新点 C)。

提供:
  - `linear_sum_assignment`: 纯 Python/numpy 的匹配算法(最小化总代价),无 scipy 依赖。
  - `TreeRecord`: 参与匹配的最小单木表示(位置/树高/冠幅/物种)。
  - `match_trees`: 位置门控 + 代价(位置+冠幅+树高+物种) + 医牛利最优求解,
    超大规模或显式关闭时回退贪婪基线;输出配对/新生/枯死。
纯函数设计,均可单测。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from ..logging_setup import get_logger

log = get_logger(__name__)

# 门控外的禁止配对代价(有限大值,保证算法不受 inf 干扰)。
_BIG = 1e9
# 超过该规模的代价矩阵改走贪婪(避免 O(n^2 m) 在极大地块上起飞)。
_GREEDY_CELL_LIMIT = 200_000


def linear_sum_assignment(cost) -> tuple[list[int], list[int]]:
    """最小化总代价的分配(标准 O(n^2 m) 潜势法)。

    参数 cost: n×m 二维序列(有限值)。返回 (row_idx, col_idx) 两个等长列表,
    表示 row_idx[k] 行 与 col_idx[k] 列配对。仅返回 min(n,m) 个配对。
    """
    n = len(cost)
    if n == 0:
        return [], []
    m = len(cost[0])
    if m == 0:
        return [], []
    transposed = False
    c = cost
    if n > m:  # 算法要求行数 <= 列数
        c = [[cost[i][j] for i in range(n)] for j in range(m)]
        n, m = m, n
        transposed = True
    INF = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)   # p[j] = 分配给列 j 的行(1-indexed),0 为哨兵
    way = [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = INF
            j1 = -1
            for j in range(1, m + 1):
                if not used[j]:
                    cur = c[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    pairs = [(p[j] - 1, j - 1) for j in range(1, m + 1) if p[j] > 0]
    if transposed:
        pairs = [(j, i) for (i, j) in pairs]
    pairs.sort()
    return [i for i, _ in pairs], [j for _, j in pairs]


@dataclass
class TreeRecord:
    """参与匹配的单木最小表示。x/y 为同一坐标系(像素或世界)下的位置。"""

    key: str
    x: float
    y: float
    height: Optional[float] = None
    crown: Optional[float] = None
    species: Optional[str] = None
    individual_id: Optional[str] = None


@dataclass
class MatchResult:
    pairs: list[tuple[int, int]]   # (prev_idx, curr_idx)
    births: list[int]              # curr 中未配对(新生)
    deaths: list[int]              # prev 中未配对(枯死/遗漏)
    total_cost: float


def _pair_cost(
    a: TreeRecord,
    b: TreeRecord,
    *,
    max_dist: float,
    w_pos: float,
    w_crown: float,
    w_height: float,
    species_penalty: float,
) -> float:
    """单对代价。超过位置门控返回 _BIG(禁止配对)。"""
    d = math.hypot(a.x - b.x, a.y - b.y)
    if d > max_dist:
        return _BIG
    cost = w_pos * (d / max_dist if max_dist > 0 else 0.0)
    if a.crown is not None and b.crown is not None:
        denom = max(a.crown, b.crown, 1e-6)
        cost += w_crown * abs(a.crown - b.crown) / denom
    if a.height is not None and b.height is not None:
        denom = max(a.height, b.height, 1e-6)
        cost += w_height * abs(a.height - b.height) / denom
    if a.species and b.species and a.species != b.species:
        cost += species_penalty
    return cost


def build_cost_matrix(
    prev: list[TreeRecord],
    curr: list[TreeRecord],
    *,
    max_dist: float,
    w_pos: float = 1.0,
    w_crown: float = 0.3,
    w_height: float = 0.3,
    species_penalty: float = 0.5,
) -> list[list[float]]:
    return [
        [
            _pair_cost(
                a, b, max_dist=max_dist, w_pos=w_pos, w_crown=w_crown,
                w_height=w_height, species_penalty=species_penalty,
            )
            for b in curr
        ]
        for a in prev
    ]


def _greedy_pairs(cost: list[list[float]]) -> list[tuple[int, int]]:
    cand = []
    for i, row in enumerate(cost):
        for j, c in enumerate(row):
            if c < _BIG:
                cand.append((c, i, j))
    cand.sort()
    up: set[int] = set()
    uc: set[int] = set()
    out = []
    for _c, i, j in cand:
        if i in up or j in uc:
            continue
        out.append((i, j))
        up.add(i)
        uc.add(j)
    return out


def match_trees(
    prev: list[TreeRecord],
    curr: list[TreeRecord],
    *,
    max_dist: float,
    w_pos: float = 1.0,
    w_crown: float = 0.3,
    w_height: float = 0.3,
    species_penalty: float = 0.5,
    use_hungarian: bool = True,
) -> MatchResult:
    """位置门控 + 多特征代价的跨时相匹配。

    优先医牛利最优求解;超大规模或 use_hungarian=False 时回退贪婪。
    仅接受门控内(代价<_BIG)的配对;未配对 prev=枯死、curr=新生。
    """
    np_ = len(prev)
    nc = len(curr)
    if np_ == 0 or nc == 0:
        return MatchResult(pairs=[], births=list(range(nc)), deaths=list(range(np_)), total_cost=0.0)
    cost = build_cost_matrix(
        prev, curr, max_dist=max_dist, w_pos=w_pos, w_crown=w_crown,
        w_height=w_height, species_penalty=species_penalty,
    )
    if use_hungarian and np_ * nc <= _GREEDY_CELL_LIMIT:
        rows, cols = linear_sum_assignment(cost)
        raw = list(zip(rows, cols))
        solver = "hungarian"
    else:
        raw = _greedy_pairs(cost)
        solver = "greedy"
    pairs = [(i, j) for (i, j) in raw if cost[i][j] < _BIG]
    total = sum(cost[i][j] for (i, j) in pairs)
    matched_prev = {i for i, _ in pairs}
    matched_curr = {j for _, j in pairs}
    births = [j for j in range(nc) if j not in matched_curr]
    deaths = [i for i in range(np_) if i not in matched_prev]
    log.info(
        "[lifecycle] 匹配(%s): prev=%d curr=%d 配对=%d 新生=%d 枯死=%d 总代价=%.3f",
        solver, np_, nc, len(pairs), len(births), len(deaths), total,
    )
    return MatchResult(pairs=pairs, births=births, deaths=deaths, total_cost=total)
