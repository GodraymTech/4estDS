"""报告指标层（阶段六）：纯 Python 统计，可单测、无重依赖。

从一批观测 dict（db.reader.fetch_observations 的输出）计算专业指标：
- 株数 / 每公顷密度
- 物种组成
- 冠幅尺寸分布（复用 logging_setup.summarize_distribution）
- 置信度分布
- 树高分布（如有 CHM）
- 离散尺度档占比（创新点 A 的 slice_size 统计）

设计原则：输入仅依赖普通 dict，不耦合 sqlite / ORM，便于单测与复用。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..logging_setup import summarize_distribution


def _num(v) -> float | None:
    """宽松取数：None / 非数 -> None。"""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def species_composition(observations: list[dict]) -> dict[str, int]:
    """按物种统计株数（None/空 -> 'unknown'），按株数降序。"""
    counts: dict[str, int] = {}
    for o in observations:
        sp = (o.get("species") or "unknown").strip() or "unknown"
        counts[sp] = counts.get(sp, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def density_per_hectare(tree_count: int, area_m2: float | None) -> float | None:
    """每公顷株数。area_m2<=0 或缺失 -> None（不编造数据）。"""
    a = _num(area_m2)
    if a is None or a <= 0:
        return None
    return tree_count / (a / 10000.0)


def scale_class_breakdown(observations: list[dict]) -> dict[str, dict]:
    """按 slice_size（四叉树切片边长）统计档位占比。

    创新点 A 的可解释性：哪个尺度档位贡献了多少检出。
    返回 {slice_size_str: {'count': n, 'ratio': r}}。
    """
    buckets: dict[str, int] = {}
    for o in observations:
        ss = o.get("slice_size")
        key = str(int(ss)) if ss not in (None, "") else "unknown"
        buckets[key] = buckets.get(key, 0) + 1
    total = sum(buckets.values()) or 1
    ordered = sorted(
        buckets.items(),
        key=lambda kv: (kv[0] == "unknown", int(kv[0]) if kv[0].isdigit() else 0),
    )
    return {k: {"count": v, "ratio": v / total} for k, v in ordered}


@dataclass
class ReportData:
    """一份报告的结构化结果（与渲染层解耦）。"""

    tract_id: str | None
    run_id: str | None
    tree_count: int
    species: dict[str, int]
    density_per_ha: float | None
    crown_w_px: dict
    crown_h_px: dict
    crown_area_px: dict
    confidence: dict
    height: dict
    scale_classes: dict[str, dict]
    meta: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "tract_id": self.tract_id,
            "run_id": self.run_id,
            "tree_count": self.tree_count,
            "species": self.species,
            "density_per_ha": self.density_per_ha,
            "crown_w_px": self.crown_w_px,
            "crown_h_px": self.crown_h_px,
            "crown_area_px": self.crown_area_px,
            "confidence": self.confidence,
            "height": self.height,
            "scale_classes": self.scale_classes,
            "meta": self.meta,
        }


def _collect(observations: list[dict], key: str) -> list[float]:
    out: list[float] = []
    for o in observations:
        v = _num(o.get(key))
        if v is not None:
            out.append(v)
    return out


def compute_report(
    observations: list[dict],
    *,
    tract: dict | None = None,
    run_id: str | None = None,
) -> ReportData:
    """从观测记录计算一份完整报告数据。"""
    tract = tract or {}
    area_m2 = _num(tract.get("geo_area"))
    species = species_composition(observations)
    n = len(observations)
    data = ReportData(
        tract_id=tract.get("tract_id"),
        run_id=run_id,
        tree_count=n,
        species=species,
        density_per_ha=density_per_hectare(n, area_m2),
        crown_w_px=summarize_distribution(_collect(observations, "crown_w_px")),
        crown_h_px=summarize_distribution(_collect(observations, "crown_h_px")),
        crown_area_px=summarize_distribution(_collect(observations, "crown_area_px")),
        confidence=summarize_distribution(_collect(observations, "confidence")),
        height=summarize_distribution(_collect(observations, "height")),
        scale_classes=scale_class_breakdown(observations),
        meta={
            "acquisition_time": tract.get("acquisition_time"),
            "location": tract.get("location"),
            "area_m2": area_m2,
            "pixel_w": tract.get("pixel_w"),
            "pixel_h": tract.get("pixel_h"),
            "species_richness": len(species),
        },
    )
    return data
