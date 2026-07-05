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
    crown_w_geo: dict
    crown_h_geo: dict
    crown_area_geo: dict
    confidence: dict
    height: dict
    crown_volume_geo: dict
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
            "crown_w_geo": self.crown_w_geo,
            "crown_h_geo": self.crown_h_geo,
            "crown_area_geo": self.crown_area_geo,
            "confidence": self.confidence,
            "height": self.height,
            "crown_volume_geo": self.crown_volume_geo,
            "scale_classes": self.scale_classes,
            "meta": self.meta,
        }


def _collect(observations: list[dict], key: str) -> list[float]:
    out: list[float] = []
    for o in observations:
        v = _num(o.get(key))
        if v is not None:
            if key == "height" and v > 50.0:
                continue
            out.append(v)
    return out


def compute_report(
    observations: list[dict],
    *,
    tract: dict | None = None,
    run_id: str | None = None,
) -> ReportData:
    """从观测记录计算一份完整报告数据。"""
    # Map legacy keys to physical/real measurements for compatibility with rendering and calculations
    for o in observations:
        if "crown_area_px" not in o or o["crown_area_px"] is None:
            o["crown_area_px"] = o.get("crown_area_px_real")
        if "crown_area_geo" not in o or o["crown_area_geo"] is None:
            o["crown_area_geo"] = o.get("crown_area_geo_real")
        if "crown_volume_geo" not in o or o["crown_volume_geo"] is None:
            o["crown_volume_geo"] = o.get("crown_volume_geo_real")

    tract = tract or {}
    area_m2 = _num(tract.get("geo_area"))
    species = species_composition(observations)
    n = len(observations)
    
    # 算林冠郁闭度所需的累加
    all_crown_areas = [
        _num(o.get("crown_area_geo")) 
        for o in observations 
        if _num(o.get("crown_area_geo")) is not None
    ]
    total_crown_area = sum(all_crown_areas) if all_crown_areas else 0.0
    canopy_cover_rate = None
    if area_m2 and area_m2 > 0 and total_crown_area > 0:
        canopy_cover_rate = total_crown_area / area_m2

    # 树种深度交叉统计分析
    from collections import defaultdict
    sp_obs = defaultdict(list)
    for o in observations:
        sp = (o.get("species") or "unknown").strip() or "unknown"
        sp_obs[sp].append(o)
        
    species_analysis = {}
    for sp, obs_list in sp_obs.items():
        heights = [float(o["height"]) for o in obs_list if _num(o.get("height")) is not None]
        volumes = [float(o["crown_volume_geo"]) for o in obs_list if _num(o.get("crown_volume_geo")) is not None]
        crown_areas = [float(o["crown_area_geo"]) for o in obs_list if _num(o.get("crown_area_geo")) is not None]
        
        # 相对多度 (RA)
        ra = len(obs_list) / n if n else 0.0
        # 相对盖度 (RC)
        sp_total_area = sum(crown_areas) if crown_areas else 0.0
        rc = sp_total_area / total_crown_area if total_crown_area > 0 else 0.0
        # 重要值 (IV)
        iv = (ra + rc) / 2.0
        
        avg_h = sum(heights) / len(heights) if heights else None
        avg_v = sum(volumes) / len(volumes) if volumes else None
        avg_a = sum(crown_areas) / len(crown_areas) if crown_areas else None
        
        # 冠层饱满度因子 (FI)
        fi = avg_v / avg_a if (avg_a and avg_v and avg_a > 0) else None

        species_analysis[sp] = {
            "count": len(obs_list),
            "ratio": ra,
            "ra": ra,
            "rc": rc,
            "iv": iv,
            "fi": fi,
            "density_per_ha": density_per_hectare(len(obs_list), area_m2),
            "total_crown_area": sp_total_area,
            "total_volume": sum(volumes) if volumes else 0.0,
            "avg_height": avg_h,
            "max_height": max(heights) if heights else None,
            "avg_volume": avg_v,
            "max_volume": max(volumes) if volumes else None,
            "avg_crown_area": avg_a,
            "crown_w_geo": summarize_distribution(_collect(obs_list, "crown_w_geo")),
            "crown_h_geo": summarize_distribution(_collect(obs_list, "crown_h_geo")),
            "crown_area_geo": summarize_distribution(_collect(obs_list, "crown_area_geo")),
            "height": summarize_distribution(_collect(obs_list, "height")),
        }

    data = ReportData(
        tract_id=tract.get("tract_id"),
        run_id=run_id,
        tree_count=n,
        species=species,
        density_per_ha=density_per_hectare(n, area_m2),
        crown_w_px=summarize_distribution(_collect(observations, "crown_w_px")),
        crown_h_px=summarize_distribution(_collect(observations, "crown_h_px")),
        crown_area_px=summarize_distribution(_collect(observations, "crown_area_px")),
        crown_w_geo=summarize_distribution(_collect(observations, "crown_w_geo")),
        crown_h_geo=summarize_distribution(_collect(observations, "crown_h_geo")),
        crown_area_geo=summarize_distribution(_collect(observations, "crown_area_geo")),
        confidence=summarize_distribution(_collect(observations, "confidence")),
        height=summarize_distribution(_collect(observations, "height")),
        crown_volume_geo=summarize_distribution(_collect(observations, "crown_volume_geo")),
        scale_classes=scale_class_breakdown(observations),
        meta={
            "acquisition_time": tract.get("acquisition_time"),
            "location": tract.get("location"),
            "area_m2": area_m2,
            "pixel_w": tract.get("pixel_w"),
            "pixel_h": tract.get("pixel_h"),
            "species_richness": len(species),
            "species_analysis": species_analysis,
            "canopy_cover_rate": canopy_cover_rate,
            "total_crown_area": total_crown_area,
            "raw_observations": [
                {
                    "species": (o.get("species") or "unknown").strip() or "unknown",
                    "height": _num(o.get("height")),
                    "volume": _num(o.get("crown_volume_geo")),
                    "crown_area": _num(o.get("crown_area_geo")),
                    "confidence": _num(o.get("confidence"))
                }
                for o in observations
            ]
        },
    )
    return data
