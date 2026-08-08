"""API 请求/响应模型。

与 contracts.py 的域 DTO 分开：这里是 *传输层* 形状(HTTP 边界)，避免把 Web 关心
泄露到域模型(SOLID: 关注分离)。推理请求复用 contracts.InferenceRequest 的子集字段。
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union

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
    phase_id: Optional[str] = Field(None, description="地块时相 YYYYMMDD")
    tract_id: Optional[str] = None
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
    phase_id: Optional[str] = None
    phase_source: Optional[str] = None


class InputInspectOut(BaseModel):
    input_path: str
    normalized_path: str
    input_kind: str
    image_count: int
    suggested_tract_id: Optional[str] = None
    suggested_phase_id: Optional[str] = None
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
    tract_id: Optional[str] = None
    phase_id: Optional[str] = None
    tiff_id: Optional[str] = None
    geo_area: Optional[float] = None
    area_unit: Optional[str] = None
    observation_count: int = 0
    error: Optional[str] = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class CancelJobOut(BaseModel):
    job_id: str
    status: JobStatus
    message: str


class CancelAllJobsOut(BaseModel):
    cancelled: int = 0
    purged_queues: list[str] = Field(default_factory=list)
    message: str


class WorkerStopOut(CancelAllJobsOut):
    worker_pids: list[int] = Field(default_factory=list)
    worker_found: bool = False


class ArtifactNode(BaseModel):
    key: str
    name: str
    path: str
    type: str
    size: Optional[int] = None
    previewable: bool = False
    description: Optional[str] = None
    children: list["ArtifactNode"] = Field(default_factory=list)


class ArtifactTreeOut(BaseModel):
    run_id: str
    run_dir: Optional[str] = None
    available: bool = False
    tree: list[ArtifactNode] = Field(default_factory=list)


class ArtifactExportRequest(BaseModel):
    paths: list[str] = Field(default_factory=list, description="相对 run_dir 的文件或目录路径；空列表表示全量导出")


class ArtifactExportOut(BaseModel):
    run_id: str
    filename: str
    url: str


class TractOut(BaseModel):
    """地块台账行(宽松字段，直接透传 reader 行)。"""

    model_config = {"extra": "allow"}

    tract_id: str
    phase_id: Optional[str] = None
    geo_area: Optional[float] = None
    area_unit: Optional[str] = None
    crs_epsg: Optional[int] = None
    active_run_id: Optional[str] = None
    status: Optional[str] = None


class EffectiveAreaPut(BaseModel):
    """保存当前地块唯一有效区域；updated_at 用于乐观并发。"""

    geometry: dict[str, Any]
    updated_at: str = Field(..., min_length=1)
    clip_to_boundary: bool = False


class EffectiveAreaOut(BaseModel):
    tract_pk: str
    boundary_geometry: dict[str, Any]
    geometry: dict[str, Any]
    tract_area_hm2: float
    tract_phase_area_hm2: float = 0.0
    effective_area_hm2: float
    effective_ratio: float
    updated_at: str
    warnings: tuple[str, ...] = ()
    is_default: bool


class EffectiveAreaImportOut(BaseModel):
    tract_pk: str
    geometry: dict[str, Any]
    source_crs: str
    target_crs: str
    feature_count: int
    polygon_count: int
    layer: Optional[str] = None
    layers: tuple[str, ...] = ()
    effective_area_hm2: float
    effective_ratio: float
    requires_clip: bool
    warnings: tuple[str, ...] = ()


class ReviewCreate(BaseModel):
    phase_id: str = Field(..., pattern=r"^\d{8}$")
    tiff_id: str = Field(..., min_length=1)
    mode: Literal["inherit", "fresh"] = "inherit"
    base_run_id: Optional[str] = None


class ReviewOperationBatch(BaseModel):
    revision: int = Field(..., ge=0)
    operation_id: str = Field(..., min_length=1)
    operations: list[dict[str, Any]] = Field(..., min_length=1)


class ReviewMaskStroke(BaseModel):
    mode: Literal["add", "erase"]
    x: float
    y: float
    radius: float = Field(..., gt=0)


class ReviewMaskOperation(BaseModel):
    revision: int = Field(..., ge=0)
    operation_id: str = Field(..., min_length=1)
    item_id: str = Field(..., min_length=1)
    strokes: list[ReviewMaskStroke] = Field(..., min_length=1)


class ReviewRevisionCommand(BaseModel):
    revision: int = Field(..., ge=0)
    operation_id: str = Field(..., min_length=1)


class ReviewCancelCommand(BaseModel):
    revision: int = Field(..., ge=0)


class ReviewSessionOut(BaseModel):
    session_id: str
    phase_id: str
    tiff_id: str
    tract_phase_pk: str
    mode: Literal["inherit", "fresh"]
    base_run_id: Optional[str] = None
    expected_active_run_id: Optional[str] = None
    status: str
    revision: int
    published_run_id: Optional[str] = None
    created_at: str
    updated_at: str
    image_name: Optional[str] = None
    city: Optional[str] = None
    tract_id: Optional[str] = None


class ReviewWorkspaceOut(BaseModel):
    revision: int
    items: list[dict[str, Any]] = Field(default_factory=list)
    category_catalog: list[dict[str, Any]] = Field(default_factory=list)
    visible_categories: list[str] = Field(default_factory=list)
    active_category: Optional[str] = None
    text_prompts: list[dict[str, Any]] = Field(default_factory=list)
    visual_exemplars: list[dict[str, Any]] = Field(default_factory=list)
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    total_items: int = 0
    page_offset: int = 0
    page_limit: Optional[int] = None


class ReviewPatchOut(BaseModel):
    session_id: str
    revision: int
    items: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)
    changed_items: list[dict[str, Any]] = Field(default_factory=list)
    deleted_item_ids: list[str] = Field(default_factory=list)
    replace_all: bool = False


class ReviewPublishOut(BaseModel):
    session_id: str
    run_id: str
    observation_count: int
    status: str


class ReviewRegionScope(BaseModel):
    """以图像像素为准的正方形识别范围。"""

    type: Literal["region"]
    center_px: tuple[float, float]
    side_px: float = Field(..., gt=0)


class ReviewFullScope(BaseModel):
    """全图识别范围。"""

    type: Literal["full"]


ReviewAttemptScope = Annotated[
    Union[ReviewRegionScope, ReviewFullScope],
    Field(discriminator="type"),
]


class ReviewAttemptCreate(BaseModel):
    revision: int = Field(..., ge=0)
    prompt_type: Literal["text", "visual"]
    prompts: list[dict[str, Any]] = Field(default_factory=list)
    visual_exemplars: list[dict[str, Any]] = Field(default_factory=list)
    scope: ReviewAttemptScope
    merge_mode: Literal["append", "replace_all"] = "append"
    threshold: float = Field(0.25, ge=0, le=1)


class ReviewAttemptApply(BaseModel):
    revision: int = Field(..., ge=0)
    merge_mode: Optional[Literal["append", "replace_all"]] = None


class ReviewAttemptExpand(BaseModel):
    revision: int = Field(..., ge=0)


class ReviewAttemptOut(BaseModel):
    model_config = {"extra": "allow"}

    attempt_id: str
    status: str
    prompt_type: str
    scope: dict[str, Any]
    merge_mode: str
    threshold: float
    progress: int = 0
    completed_windows: int = 0
    total_windows: int = 0
    candidate_count: int = 0
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None


class TiffOut(BaseModel):
    """TIFF 影像资产行(地图标注与看板聚合的影像维度事实源)。"""
    model_config = {"extra": "allow"}
    tract_id: str
    tract_phase_pk: str
    phase_id: str
    tiff_id: str
    file_name: Optional[str] = None
    source_path: Optional[str] = None
    path_exists: bool = False
    tiff_type: Optional[Literal["normal", "tiled", "ext_ovr", "COG", "invalid"]] = None
    center_geom: Optional[str] = None
    center_lng: Optional[float] = None
    center_lat: Optional[float] = None
    crs_epsg: Optional[int] = None
    crs_wkt: Optional[str] = None
    geotransform: Optional[str] = None
    pixel_width: Optional[int] = None
    pixel_height: Optional[int] = None
    gsd: Optional[float] = None
    geo_area: Optional[float] = None
    area_unit: Optional[str] = None
    band_count: Optional[int] = None
    dtype: Optional[str] = None
    nodata: Optional[float] = None
    observation_count: int = 0
    active_run_id: Optional[str] = None
    run_id: Optional[str] = None
    run_count: int = 0
    run_status_counts: dict[str, int] = Field(default_factory=dict)
    active_run_status: Optional[str] = None
    detected_at: Optional[str] = None
    status: str = "未检测"
    has_detection: bool = False


class TractImageryOut(BaseModel):
    """地块多时相真影像瓦片配置(供前端时相卷帘刷开真影像)。

    tiles 为空 / available=False 时前端回退默认底图, 保证降级可用。
    """

    tract_id: str
    phase_id: Optional[str] = None
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
    tract_phase_pk: Optional[str] = None
    phase_id: Optional[str] = None
    run_id: Optional[str] = None
    tree_count: int = 0
    species: dict[str, int] = Field(default_factory=dict)
    density_per_ha: Optional[float] = None
    crown_width_geo: dict[str, Any] = Field(default_factory=dict)
    crown_height_geo: dict[str, Any] = Field(default_factory=dict)
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


class AssetInspectRequest(BaseModel):
    input_path: Optional[str] = None
    lng: Optional[float] = None
    lat: Optional[float] = None


class AssetInspectOut(BaseModel):
    input_path: Optional[str] = None
    normalized_path: Optional[str] = None
    exists: bool = False
    inspect_error: Optional[str] = None
    image_name: Optional[str] = None
    suggested_tract_id: Optional[str] = None
    suggested_phase_id: Optional[str] = None
    city: Optional[str] = None
    county: Optional[str] = None
    town: Optional[str] = None
    region_id: Optional[str] = None
    lng: Optional[float] = None
    lat: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    crs_epsg: Optional[int] = None
    tiff_type: Optional[
        Literal[
            "normal",
            "tiled",
            "ext_ovr",
            "COG",
            "invalid",
        ]
    ] = None
    tiff_type_label: Optional[str] = None
    cog_required: bool = False
    suggested_cog_path: Optional[str] = None
    suggested_cog_display_path: Optional[str] = None
    geo_error: Optional[str] = None
    estimated_cog_seconds: Optional[float] = None


class AssetCogConvertRequest(BaseModel):
    input_path: str


class AssetCogConvertOut(BaseModel):
    input_path: str
    source_path: str
    source_display_path: str
    cog_path: str
    cog_display_path: str
    tiff_type: str
    tiff_type_label: str
    converted: bool = False


class AssetTiffCreate(BaseModel):
    input_path: str
    city: Optional[str] = None
    county: Optional[str] = None
    town: Optional[str] = None
    tract_id: Optional[str] = None
    phase_id: Optional[str] = None
    image_name: Optional[str] = None


class AssetPatch(BaseModel):
    city: Optional[str] = None
    county: Optional[str] = None
    town: Optional[str] = None
    tract_id: Optional[str] = None
    phase_id: Optional[str] = None
    image_name: Optional[str] = None
    new_path: Optional[str] = None
    tiff_type: Optional[Literal["normal", "tiled", "ext_ovr", "COG", "invalid"]] = None


class AssetDeletePreview(BaseModel):
    phase_id: str
    tiff_id: str
    observation_count: int = 0
    requires_confirmation: bool = False


class AssetRow(BaseModel):
    model_config = {"extra": "allow"}

    city: Optional[str] = None
    county: Optional[str] = None
    town: Optional[str] = None
    region_id: Optional[str] = None
    tract_pk: Optional[str] = None
    tract_id: Optional[str] = None
    tract_phase_pk: Optional[str] = None
    phase_id: Optional[str] = None
    tiff_id: Optional[str] = None
    image_name: Optional[str] = None
    source_path: Optional[str] = None
    tiff_type: Optional[Literal["normal", "tiled", "ext_ovr", "COG", "invalid"]] = None
    run_id: Optional[str] = None
    active_run_id: Optional[str] = None
    run_count: int = 0
    run_status_counts: dict[str, int] = Field(default_factory=dict)
    active_run_status: Optional[str] = None
    footprint_area_hm2: Optional[float] = None
    area_hm2: Optional[float] = None
    geo_area: Optional[float] = None
    effective_area_hm2: Optional[float] = None
    tract_area_hm2: Optional[float] = None
    tract_phase_area_hm2: Optional[float] = None
    observation_count: int = 0
    detected_at: Optional[str] = None
    pixel_width: Optional[int] = None
    pixel_height: Optional[int] = None
    estimated_cog_seconds: Optional[float] = None


class GeoPlaceOut(BaseModel):
    id: str
    name: str
    address: Optional[str] = None
    city: Optional[str] = None
    county: Optional[str] = None
    town: Optional[str] = None
    adcode: Optional[str] = None
    lng: float
    lat: float
    source: str


class GeoSearchOut(BaseModel):
    query: str
    places: list[GeoPlaceOut] = Field(default_factory=list)


class GeoReverseOut(BaseModel):
    lng: float
    lat: float
    city: str
    county: str
    town: str
    region_id: str
    formatted_address: Optional[str] = None
    adcode: Optional[str] = None


class ServerFileItem(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: Optional[int] = None


class ServerFileBrowseOut(BaseModel):
    current_path: str
    parent_path: Optional[str] = None
    items: list[ServerFileItem] = Field(default_factory=list)


class TreeObservationItemOut(BaseModel):
    observation_id: str
    individual_id: Optional[str] = None
    run_id: str
    tract_phase_pk: str
    tiff_id: Optional[str] = None
    phase_id: Optional[str] = None
    species: Optional[str] = None
    confidence: Optional[float] = None
    center_geom: Optional[str] = None
    crown_geom: Optional[str] = None
    box_px: Optional[str] = None
    box_px_sub: Optional[str] = None
    box_geo: Optional[str] = None
    crown_width_px: Optional[float] = None
    crown_height_px: Optional[float] = None
    crown_width_geo: Optional[float] = None
    crown_height_geo: Optional[float] = None
    crown_area_px: Optional[float] = None
    crown_area_geo_est: Optional[float] = None
    crown_area_geo_real: Optional[float] = None
    height: Optional[float] = None
    height_source: Optional[str] = None
    source: str = "infer"
    crown_volume_geo_est: Optional[float] = None
    crown_volume_geo_real: Optional[float] = None
    source_subimage_path: Optional[str] = None
    slice_size: Optional[int] = None
    created_at: str
    tract_id: Optional[str] = None
    city: Optional[str] = None
    county: Optional[str] = None
    town: Optional[str] = None


class TreeObservationListOut(BaseModel):
    items: list[TreeObservationItemOut] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
    available_species: list[str] = Field(default_factory=list)

