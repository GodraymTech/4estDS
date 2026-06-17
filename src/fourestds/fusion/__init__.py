"""多源融合层(创新点 B,阶段七骨架)。

RGB + CHM/多光谱跨模态融合:检测框 -> 冠幅多边形;CHM = DSM - DEM 给出树高。
TODO(阶段七): 配准、框->分割、CHM 采样求树高、多光谱物种特征。
"""
from __future__ import annotations


def tree_height_from_chm(dsm: float, dem: float) -> float:
    """树高 = DSM - DEM(负值裁到 0)。纯标量计算,可单测。"""
    return max(0.0, dsm - dem)
