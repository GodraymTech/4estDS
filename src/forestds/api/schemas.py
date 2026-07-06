"""API 请求/响应模型。

与 contracts.py 的域 DTO 分开：这里是 *传输层* 形状(HTTP 边界)，避免把 Web 关心
泄露到域模型(SOLID: 关注分离)。推理请求复用 contracts.InferenceRequest 的子集字段。
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from ..contracts import ExportFormat, JobStatus


class UploadResponse(BaseModel):
    key: str = Field(..., description="存储对象 key，提交推理时回传")
    filename: str
    size: int


class InferSubmit(BaseModel):
    """提交推理作业的请求体。

    ``image_key`` 来自 /uploads；``input_path`` 是后端/Worker 可访问的本地路径。
    二者二选一，路由层负责进一步校验存在性与批量路由。
    """

    image_key: Optional[str] = Field(None, description="已上传影像的存储 key")
    input_path: Optional[str] = Field(None, description="本地影像文件或目录路径")
    arch: Optional[str] = None
    acquisition_time: Optional[str] = Field(None, description="地块时相 YYYYmmdd")
    location: Optional[str] = None
    tile_size: Optional[int] = Field(None, ge=1)
    overlap_rate: Optional[float] = Field(None, ge=0.0, le=0.5)
    dsm: Optional[str] = None
    dem: Optional[str] = None
    las: Optional[str] = None
    export_fmt: Optional[ExportFormat] = None


class InputInspectRequest(BaseModel):
    input_path: str = Field(..., description="本地影像文件或目录路径")


class InputInspectImage(BaseModel):
    path: str
    stem: str
    width: Optional[int] = None
    height: Optional[int] = None
    crs_epsg: Optional[int] = None
    acquisition_time: Optional[str] = None
    acquisition_time_source: Optional[str] = None


class InputInspectOut(BaseModel):
    input_path: str
    normalized_path: str
    input_kind: str
    image_count: int
    suggested_location: Optional[str] = None
    suggested_acquisition_time: Optional[str] = None
    images: list[InputInspectImage] = Field(default_factory=list)


class JobRef(BaseModel):
    job_id: str = Field(..., description="作业标识(即 run_id)")
    status: JobStatus


class JobLogsOut(BaseModel):
    job_id: str
    cursor: int = 0
    lines: list[str] = Field(default_factory=list)
    available: bool = False


class JobStatusOut(BaseModel):
    job_id: str
    status: JobStatus
    tract_id: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_s: Optional[float] = None
    error: Optional[str] = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class JobHistoryItem(BaseModel):
    run_id: str
    task_type: str
    status: JobStatus
    model_arch: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_s: Optional[float] = None
    input_path: Optional[str] = None
    error: Optional[str] = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class CancelJobOut(BaseModel):
    job_id: str
    status: JobStatus
    message: str


class TractOut(BaseModel):
    """地块台账行(宽松字段，直接透传 reader 行)。"""

    model_config = {"extra": "allow"}

    tract_id: str
    name: Optional[str] = None
    acquisition_time: Optional[str] = None
    location: Optional[str] = None
    geo_area: Optional[float] = None
    area_unit: Optional[str] = None
    crs_epsg: Optional[int] = None
    active_run_id: Optional[str] = None
    status: Optional[str] = None


class TractImageryOut(BaseModel):
    """地块多时相真影像瓦片配置(供前端时相卷帘刷开真影像)。

    tiles 为空 / available=False 时前端回退默认底图, 保证降级可用。
    """

    tract_id: str
    acquisition_time: Optional[str] = None
    tiles: Optional[list[str]] = None
    tile_size: int = 256
    attribution: Optional[str] = None
    min_zoom: Optional[int] = None
    max_zoom: Optional[int] = None
    available: bool = False
    source_path: Optional[str] = None
    source_format: Optional[str] = None
    tile_service: Optional[str] = None


class TractSummaryOut(BaseModel):
    """地块统计摘要(复用 report.metrics 的结构化产物)。"""

    model_config = {"extra": "allow"}

    tract_id: Optional[str] = None
    run_id: Optional[str] = None
    tree_count: int = 0
    species: dict[str, int] = Field(default_factory=dict)
    density_per_ha: Optional[float] = None
    crown_w_geo: dict[str, Any] = Field(default_factory=dict)
    crown_h_geo: dict[str, Any] = Field(default_factory=dict)
    crown_area_geo: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)


class ChangeCompareOut(BaseModel):
    """时序变化对比(两个 run/时相)。"""

    tract_id: str
    base_run_id: Optional[str] = None
    target_run_id: Optional[str] = None
    base_count: int = 0
    target_count: int = 0
    delta_count: int = 0
    base_crown_area: Optional[float] = None
    target_crown_area: Optional[float] = None
    delta_crown_area: Optional[float] = None
