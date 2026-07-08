"""服务化契约层 (DTO / Contracts)。

职责(单一): 定义跨进程、跨层流转的数据契约，作为 CLI / Worker / API / SDK
之间的防腐层(Anti-Corruption Layer)。引擎内部以 ``dict`` 传递的 metrics 在此
被收敛为强类型结构，避免“dict 满天飞”的隐式耦合。

设计原则：
- 不依赖 typer / FastAPI / Dramatiq 任何 Web/任务框架，只用 pydantic，可被任意层引用。
- 与 ``tasks.infer.run_infer_pipeline`` 的入参/出参一一对应，保证包裹层零猜测。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

# 导出格式合法枚举（与 tasks.infer.VALID_EXPORT_FORMATS 保持一致）。
VALID_EXPORT_FORMATS: tuple[str, ...] = ("geojson", "shp", "gpkg", "csv")


class ExportFormat(str, Enum):
    """GIS 图层导出格式。"""

    geojson = "geojson"
    shp = "shp"
    gpkg = "gpkg"
    csv = "csv"


class JobType(str, Enum):
    """异步作业类型。"""

    infer = "infer"
    batch = "batch"


class JobStatus(str, Enum):
    """作业/运行状态。与 runs.status 语义对齐。"""

    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    canceled = "canceled"


class InferenceRequest(BaseModel):
    """单图推理请求。字段与 ``run_infer_pipeline`` 的关键入参一一对应。

    ``image_path`` 在入队前应已被解析为 Worker 可读的本地路径
    (对象存储场景下由 API/Worker 负责下载到共享卷后再传入)。
    """

    model_config = ConfigDict(extra="forbid")

    image_path: str = Field(..., description="输入影像本地路径 (TIFF/PNG/JPG)")
    arch: Optional[str] = Field(None, description="模型架构，默认读配置 detect.arch")
    phase_id: Optional[str] = Field(None, description="地块时相 YYYYMMDD")
    tract_id: Optional[str] = Field(None, description="地块 ID")
    tile_size: Optional[int] = Field(None, ge=1, description="手动切片边长，缺省自适应")
    overlap_rate: Optional[float] = Field(None, ge=0.0, le=0.5, description="重叠率 0~0.5")
    chm: Optional[str] = Field(None, description="CHM 栅格路径")
    dsm: Optional[str] = Field(None, description="DSM 地表高程路径")
    dem: Optional[str] = Field(None, description="DEM 裸地高程路径")
    las: Optional[str] = Field(None, description="激光点云 LAS/LAZ 路径")
    las_grid_size: Optional[float] = Field(None, gt=0, description="点云网格化分辨率(米)")
    dem_default: Optional[float] = Field(None, description="单独 DSM 模式默认背景高程")
    draw_box: Optional[bool] = Field(None, description="是否绘制检测框，缺省读配置")
    export_fmt: Optional[ExportFormat] = Field(None, description="推理后自动导出的 GIS 格式")
    publish: bool = Field(
        False,
        description="成功后是否 promote_run 发布为地块正式版本(统一规范单木)。CLI 默认 False，服务端默认置 True。",
    )

    def to_pipeline_kwargs(self) -> dict[str, Any]:
        """转为 ``run_infer_pipeline`` 的关键字参数(不含 arch / detector / run_id / settings)。"""
        return {
            "phase_id": self.phase_id,
            "tract_id": self.tract_id,
            "tile_size": self.tile_size,
            "overlap_rate": self.overlap_rate,
            "chm": self.chm,
            "dsm": self.dsm,
            "dem": self.dem,
            "las": self.las,
            "las_grid_size": self.las_grid_size,
            "dem_default": self.dem_default,
            "draw_box": self.draw_box,
            "export_fmt": self.export_fmt.value if self.export_fmt else None,
        }


class BatchInferenceRequest(BaseModel):
    """批量推理请求。``input_path`` 可为影像目录或多个入口上层收敛后的目录路径。"""

    model_config = ConfigDict(extra="forbid")

    input_path: str = Field(..., description="输入影像目录或单个影像路径")
    arch: Optional[str] = Field(None, description="模型架构，默认读配置 detect.arch")
    phase_id: Optional[str] = Field(
        None,
        description="显式地块时相 YYYYMMDD；为空时每张影像各自读取元数据默认值",
    )
    tract_id: Optional[str] = Field(
        None,
        description="批量地块 ID 前缀；为空时每张影像使用自己的文件名 stem",
    )
    tile_size: Optional[int] = Field(None, ge=1, description="手动切片边长，缺省自适应")
    overlap_rate: Optional[float] = Field(None, ge=0.0, le=0.5, description="重叠率 0~0.5")
    dsm: Optional[str] = Field(None, description="DSM 地表高程路径")
    dem: Optional[str] = Field(None, description="DEM 裸地高程路径")
    las: Optional[str] = Field(None, description="激光点云 LAS/LAZ 路径")
    export_fmt: Optional[ExportFormat] = Field(None, description="推理后自动导出的 GIS 格式")
    publish: bool = Field(False, description="成功后是否发布各单图运行结果")


class InferenceResult(BaseModel):
    """单图推理结果。是 ``run_infer_pipeline`` 返回 metrics dict 的强类型化。"""

    model_config = ConfigDict(extra="ignore")

    run_id: str
    tract_id: Optional[str] = None
    status: JobStatus = JobStatus.succeeded
    published: bool = False

    tiles_total: int = 0
    tiles_processed: int = 0
    tiles_skipped_empty: int = 0
    raw_count: int = 0
    fused_count: int = 0
    observations_written: int = 0
    duration_s: float = 0.0

    report_path: Optional[str] = None
    export_path: Optional[str] = None
    vis_path: Optional[str] = None

    @classmethod
    def from_metrics(
        cls,
        metrics: dict[str, Any],
        *,
        status: JobStatus = JobStatus.succeeded,
        published: bool = False,
    ) -> "InferenceResult":
        """从 run_infer_pipeline 的返回 dict 构造结果 DTO(容忍额外键)。"""
        data = dict(metrics or {})
        data["status"] = status
        data["published"] = published
        return cls.model_validate(data)
