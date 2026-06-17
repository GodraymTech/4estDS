"""统计报告层(阶段六骨架)。

TODO(阶段六): 密度/冠幅分布/树高分布/物种组成等专业指标;
matplotlib/plotly 出图;导出 PDF/HTML。统计汇总函数先用纯 Python 提供。
"""
from __future__ import annotations


def summarize_counts(species: list[str]) -> dict[str, int]:
    """按物种统计株数(纯 Python,可单测)。"""
    out: dict[str, int] = {}
    for s in species:
        out[s] = out.get(s, 0) + 1
    return out


def density_per_hectare(tree_count: int, area_m2: float) -> float:
    """每公顷株数。area_m2 为地块面积(平方米)。"""
    if area_m2 <= 0:
        return 0.0
    return tree_count / (area_m2 / 10000.0)
