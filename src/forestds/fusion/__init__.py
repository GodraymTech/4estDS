"""多源融合层（创新点 B，阶段七）。

RGB 检测 × 跨模态高程信息的融合：
  - CHM = DSM − DEM 给出冠层高度 -> 单木树高；
  - 仿射变换完成 RGB 与 CHM 的配准（不同分辨率/范围）。

实现见 chm.py。多光谱物种特征为后续扩展点。
"""
from __future__ import annotations

from .chm import (
    CHMSampler,
    build_chm_sampler,
    chm_from_dsm_dem,
    load_single_band,
    tree_height_from_chm,
)
from .crown import (
    verify_overlap,
    align_dsm_to_dom,
    estimate_canopy_contours,
)

__all__ = [
    "CHMSampler",
    "build_chm_sampler",
    "chm_from_dsm_dem",
    "load_single_band",
    "tree_height_from_chm",
    "verify_overlap",
    "align_dsm_to_dom",
    "estimate_canopy_contours",
]

