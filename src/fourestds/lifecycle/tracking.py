"""跨时相生命周期追踪与生长轨迹(阶段八 / 创新点 C 核心)。

给定同一 location 多个时相的单木快照(按时间排序),逐期医牛利匹配,
分配跨时相 individual_id,识别新生/枯死,并拟合每个个体的生长轨迹。

纯函数 + 可选 numpy(仅用于线性拟合生长率,缺失时降级为简单斜率)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..logging_setup import get_logger
from .matching import TreeRecord, match_trees

log = get_logger(__name__)


@dataclass
class GrowthPoint:
    time: str                    # 采集时相(如 202406)
    height: Optional[float] = None
    crown: Optional[float] = None
    obs_key: Optional[str] = None


@dataclass
class Individual:
    individual_id: str
    location_cluster: str
    first_seen: str
    last_seen: str
    status: str = "alive"        # alive | dead
    growth: list[GrowthPoint] = field(default_factory=list)
    # 每个时相对应的观测 key(用于回填 tract_trees.individual_id)
    members: dict[str, str] = field(default_factory=dict)

    def height_growth_rate(self) -> Optional[float]:
        """树高对时相序号的线性生长率(单位: m/时相)。不足两点返回 None。"""
        pts = [(idx, gp.height) for idx, gp in enumerate(self.growth) if gp.height is not None]
        if len(pts) < 2:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        try:
            import numpy as np  # 可选依赖

            slope = float(np.polyfit(xs, ys, 1)[0])
            return slope
        except Exception:
            # 降级:首尾差商(无 numpy 也能给出趋势)
            dx = xs[-1] - xs[0]
            return (ys[-1] - ys[0]) / dx if dx else None

    def to_growth_json(self) -> dict:
        return {
            "points": [
                {"time": gp.time, "height": gp.height, "crown": gp.crown, "obs_key": gp.obs_key}
                for gp in self.growth
            ],
            "height_growth_rate": self.height_growth_rate(),
            "n_observations": len(self.growth),
        }


@dataclass
class TrackingResult:
    individuals: list[Individual]
    n_births: int
    n_deaths: int
    n_matched: int

    @property
    def n_individuals(self) -> int:
        return len(self.individuals)


def track_sequence(
    snapshots: list[tuple[str, list[TreeRecord]]],
    *,
    location_cluster: str,
    max_dist: float,
    w_pos: float = 1.0,
    w_crown: float = 0.3,
    w_height: float = 0.3,
    species_penalty: float = 0.5,
    use_hungarian: bool = True,
) -> TrackingResult:
    """按时间顺序逐期追踪。

    snapshots: [(采集时相, [TreeRecord, ...]), ...] 须已按时间升序。
    返回 TrackingResult,其中每个 Individual.members[time]=key 用于回填规范株。
    """
    individuals: list[Individual] = []
    # active: 当前存活个体 -> 上一期的 TreeRecord(含位置,用于与下期匹配)
    active: list[tuple[Individual, TreeRecord]] = []
    seq = 0
    n_births = 0
    n_deaths = 0
    n_matched = 0

    def _new_individual(time: str, rec: TreeRecord) -> Individual:
        nonlocal seq
        seq += 1
        ind = Individual(
            individual_id=f"ind_{location_cluster}_{seq:05d}",
            location_cluster=location_cluster,
            first_seen=time,
            last_seen=time,
        )
        ind.growth.append(GrowthPoint(time=time, height=rec.height, crown=rec.crown, obs_key=rec.key))
        ind.members[time] = rec.key
        return ind

    if not snapshots:
        return TrackingResult(individuals=[], n_births=0, n_deaths=0, n_matched=0)

    # 首期:全部为新生
    t0, recs0 = snapshots[0]
    for rec in recs0:
        ind = _new_individual(t0, rec)
        individuals.append(ind)
        active.append((ind, rec))
        n_births += 1

    # 后续期:与 active 匹配
    for time, recs in snapshots[1:]:
        prev_recs = [r for _ind, r in active]
        result = match_trees(
            prev_recs, recs, max_dist=max_dist, w_pos=w_pos, w_crown=w_crown,
            w_height=w_height, species_penalty=species_penalty, use_hungarian=use_hungarian,
        )
        next_active: list[tuple[Individual, TreeRecord]] = []
        # 配对:延续同一个体
        for i, j in result.pairs:
            ind = active[i][0]
            rec = recs[j]
            ind.last_seen = time
            ind.growth.append(GrowthPoint(time=time, height=rec.height, crown=rec.crown, obs_key=rec.key))
            ind.members[time] = rec.key
            next_active.append((ind, rec))
            n_matched += 1
        # 枯死:prev 未配对 -> 不再进入 active,标记 dead
        for i in result.deaths:
            ind = active[i][0]
            if ind.status != "dead":
                ind.status = "dead"
                n_deaths += 1
        # 新生:curr 未配对 -> 新个体
        for j in result.births:
            rec = recs[j]
            ind = _new_individual(time, rec)
            individuals.append(ind)
            next_active.append((ind, rec))
            n_births += 1
        active = next_active

    log.info(
        "[lifecycle] 追踪完成 location=%s 时相数=%d 个体数=%d 配对次=%d 新生=%d 枯死=%d",
        location_cluster, len(snapshots), len(individuals), n_matched, n_births, n_deaths,
    )
    return TrackingResult(
        individuals=individuals, n_births=n_births, n_deaths=n_deaths, n_matched=n_matched,
    )
