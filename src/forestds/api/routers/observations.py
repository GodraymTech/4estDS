"""单木观测记录 (tree_observations) 查询及导出端点。

提供面向大规模检测数据的高性能分页检索、多维度过滤、排序与元数据统计接口。
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query

from ..deps import get_db_url
from ..schemas import TreeObservationListOut
from ...db.reader import query_tree_observations_paginated

router = APIRouter(prefix="/observations", tags=["observations"])


@router.get("", response_model=TreeObservationListOut, summary="分页查询单木观测记录")
def list_observations(
    tiff_id: Annotated[Optional[str], Query(description="来源 TIFF 影像 ID")] = None,
    run_id: Annotated[Optional[str], Query(description="推理 Run ID")] = None,
    phase_id: Annotated[Optional[str], Query(description="时相 ID")] = None,
    tract_phase_pk: Annotated[Optional[str], Query(description="所属地块时相主键")] = None,
    tract_id: Annotated[Optional[str], Query(description="地块 ID")] = None,
    species: Annotated[Optional[str], Query(description="树种过滤")] = None,
    min_confidence: Annotated[Optional[float], Query(ge=0.0, le=1.0, description="最低置信度")] = None,
    max_confidence: Annotated[Optional[float], Query(ge=0.0, le=1.0, description="最高置信度")] = None,
    keyword: Annotated[Optional[str], Query(description="搜索 observation_id 或 individual_id")] = None,
    page: Annotated[int, Query(ge=1, description="页码(从1开始)")] = 1,
    page_size: Annotated[int, Query(ge=1, le=500, description="每页条数(建议 20/50/100)")] = 50,
    sort_by: Annotated[str, Query(description="排序字段")] = "observation_id",
    sort_order: Annotated[str, Query(description="排序方向: asc | desc")] = "asc",
    db_url: Annotated[Optional[str], Depends(get_db_url)] = None,
) -> TreeObservationListOut:
    """根据条件高效分页查询单木观测数据，并返回可用的树种元数据。"""
    res = query_tree_observations_paginated(
        tiff_id=tiff_id,
        run_id=run_id,
        phase_id=phase_id,
        tract_phase_pk=tract_phase_pk,
        tract_id=tract_id,
        species=species,
        min_confidence=min_confidence,
        max_confidence=max_confidence,
        keyword=keyword,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
        url=db_url,
    )
    return TreeObservationListOut(
        items=res["items"],
        total=res["total"],
        page=res["page"],
        page_size=res["page_size"],
        available_species=res["available_species"],
    )
