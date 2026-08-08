"""SQLAlchemy 2.0 ORM mappings for the tract-phase-TIFF model."""
from __future__ import annotations

from sqlalchemy import Float, ForeignKey, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Tract(Base):
    __tablename__ = "tracts"
    __table_args__ = (UniqueConstraint("region_id", "tract_id"),)

    tract_pk: Mapped[str] = mapped_column(String, primary_key=True)            # 内部主键 ({region_id}_{tract_id})
    region_id: Mapped[str] = mapped_column(String, nullable=False)            # 行政区划 ID (格式: 市_县)
    city: Mapped[str | None] = mapped_column(String)                            # 地级市名称
    county: Mapped[str | None] = mapped_column(String)                          # 区县名称
    town: Mapped[str | None] = mapped_column(String)                            # 乡镇/街道名称
    tract_id: Mapped[str] = mapped_column(String, nullable=False)              # 用户可见地块 ID / 名称 (同 region_id 内唯一)
    boundary_geom: Mapped[str | None] = mapped_column(Text)                    # 地块默认矢量边界多边形/外接矩形 (GeoJSON/WKT)
    boundary_geom_cent: Mapped[str | None] = mapped_column(Text)               # 地块边界中心点坐标 (GeoJSON/WKT)
    effective_geom: Mapped[str | None] = mapped_column(Text)                  # 有效林地边界多边形 (GeoJSON/WKT). 'effective_source'默认时, 它等于'boundary_geom'
    effective_area_hm2: Mapped[float | None] = mapped_column(Float)            # 有效林地面积 (单位: 公顷 hm²). 默认时, 它来自'tract下 tiffs数量最多的那个时相下的所有 tiffs.effective_area_hm2 的直接面积和'
    effective_source: Mapped[str] = mapped_column(String, default="default")  # 有效区域来源 (default / manual)
    coverage_status: Mapped[str] = mapped_column(String, default="none")      # 影像覆盖状态 (none / partial / full)
    notes: Mapped[str | None] = mapped_column(Text)                            # 备注说明信息
    created_at: Mapped[str] = mapped_column(String, nullable=False)            # 创建时间 (ISO 8601)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)            # 更新时间 (ISO 8601)

    phases: Mapped[list["TractPhase"]] = relationship(back_populates="tract")


class TractPhase(Base):
    __tablename__ = "tract_phases"
    __table_args__ = (UniqueConstraint("tract_pk", "phase_id"),)

    tract_phase_pk: Mapped[str] = mapped_column(String, primary_key=True)                        # 内部主键 ({tract_pk}_{phase_id})
    tract_pk: Mapped[str] = mapped_column(ForeignKey("tracts.tract_pk", ondelete="CASCADE"))    # 所属地块外键
    region_id: Mapped[str] = mapped_column(String, nullable=False)                                # 冗余行政区划 ID
    tract_id: Mapped[str] = mapped_column(String, nullable=False)                                # 冗余地块 ID
    phase_id: Mapped[str] = mapped_column(String, nullable=False)                                # 时相 ID (固定格式: YYYYMMDD)
    area_hm2: Mapped[float | None] = mapped_column(Float, default=0.0)                            # 该时相下全量 TIFF 物理有效面积和 (hm²)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)                              # 更新时间 (ISO 8601)

    tract: Mapped[Tract] = relationship(back_populates="phases")
    tiffs: Mapped[list["Tiff"]] = relationship(back_populates="tract_phase")


class Tiff(Base):
    __tablename__ = "tiffs"

    tiff_id: Mapped[str] = mapped_column(String, primary_key=True)                                      # 5 位哈希标识 (基于规范化四角坐标生成)
    phase_id: Mapped[str] = mapped_column(String, primary_key=True)                                     # 时相 ID (固定格式: YYYYMMDD)
    tract_phase_pk: Mapped[str] = mapped_column(ForeignKey("tract_phases.tract_phase_pk", ondelete="CASCADE"))  # 所属地块时相外键
    file_name: Mapped[str | None] = mapped_column(Text)                                                 # 原始文件名 (用于展示及默认地块名提取)
    path_versions: Mapped[str] = mapped_column(Text, default="{}")                                     # 正射影像路径版本 JSON ({读取日期: 原始路径})
    multisource_path_versions: Mapped[str] = mapped_column(Text, default="{}")                         # 多源文件路径版本 JSON ({chm: {...}, dsm: {...}})
    tiff_type: Mapped[str] = mapped_column(String, default="invalid")                                  # 影像类型/有效性 (orthophoto / tile_chunk / invalid)
    footprint_geom: Mapped[str] = mapped_column(Text, nullable=False)                                  # TIFF 四角多边形 (GeoJSON/WKT, WGS84)
    footprint_bbox: Mapped[str | None] = mapped_column(Text)                                          # 覆盖范围外接矩形 JSON ([min_lng, min_lat, max_lng, max_lat])
    center_geom: Mapped[str | None] = mapped_column(Text)                                              # 影像中心点几何 (GeoJSON/WKT)
    crs_epsg: Mapped[int | None] = mapped_column(Integer)                                              # 原始坐标系 EPSG 代码
    crs_wkt: Mapped[str | None] = mapped_column(Text)                                                  # 原始坐标系 WKT 文本
    geotransform: Mapped[str | None] = mapped_column(Text)                                             # 原始仿射变换参数 JSON
    pixel_width: Mapped[int | None] = mapped_column(Integer)                                           # 图像像素宽度 (PX)
    pixel_height: Mapped[int | None] = mapped_column(Integer)                                          # 图像像素高度 (PX)
    gsd: Mapped[float | None] = mapped_column(Float)                                                    # 地面采样距离 / 分辨率 (米/像素)
    footprint_area_hm2: Mapped[float | None] = mapped_column(Float)                                     # 图像外接矩形总面积 (公顷 hm²)
    area_hm2: Mapped[float | None] = mapped_column(Float)                                               # 图像内原生非 nodata 物理有效面积 (公顷 hm²)
    effective_area_hm2: Mapped[float | None] = mapped_column(Float)                                         # 最终划界生效的真正有效面积 (公顷 hm²)
    band_count: Mapped[int | None] = mapped_column(Integer)                                            # 波段数量
    dtype: Mapped[str | None] = mapped_column(String)                                                  # 栅格数据类型 (如 uint8, float32)
    nodata: Mapped[float | None] = mapped_column(Float)                                                # 无效值 / 背景填充值
    inference_status: Mapped[str] = mapped_column(String, default="pending")                          # 推理状态 (pending / inferred)
    active_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.run_id", ondelete="SET NULL"))  # 当前发布的推理 Run 外键
    created_at: Mapped[str] = mapped_column(String, nullable=False)                                    # 创建时间 (ISO 8601)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)                                    # 更新时间 (ISO 8601)

    tract_phase: Mapped[TractPhase] = relationship(back_populates="tiffs")


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        ForeignKeyConstraint(["tiff_id", "phase_id"], ["tiffs.tiff_id", "tiffs.phase_id"], ondelete="SET NULL"),
    )

    run_id: Mapped[str] = mapped_column(String, primary_key=True)                                                       # 6 位哈希运行任务 ID
    parent_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.run_id", ondelete="SET NULL"))                  # 父 Run 外键 (子任务/批处理追踪)
    tag: Mapped[str | None] = mapped_column(String)                                                                     # 人类可读任务标签/备注
    tract_phase_pk: Mapped[str | None] = mapped_column(ForeignKey("tract_phases.tract_phase_pk", ondelete="SET NULL"))  # 关联地块时相外键
    tiff_id: Mapped[str | None] = mapped_column(String)                                                                 # 关联 TIFF 影像 ID
    phase_id: Mapped[str] = mapped_column(String, nullable=False)                                                        # 关联时相 ID
    task_type: Mapped[str] = mapped_column(String, nullable=False)                                                       # 任务类型 (infer/train/report/batch/export/postprocess/import/track)
    model_arch: Mapped[str | None] = mapped_column(String)                                                              # 模型架构名称或后端算法标识
    status: Mapped[str] = mapped_column(String, default="running")                                                      # 运行状态 (queued/running/succeeded/failed/canceled)
    slice_size: Mapped[int | None] = mapped_column(Integer)                                                             # 切片尺寸 (PX，用于推理与报告复现)
    input_path: Mapped[str | None] = mapped_column(Text)                                                                # 主输入文件/目录原始路径
    tiles_dir: Mapped[str | None] = mapped_column(Text)                                                                 # 物理切片缓存存储目录
    input_json: Mapped[str | None] = mapped_column(Text)                                                                # 任务输入元数据快照 JSON
    params_json: Mapped[str | None] = mapped_column(Text)                                                               # 任务运行参数配置快照 JSON (包含 area_method, volume_method 等)
    metrics_json: Mapped[str | None] = mapped_column(Text)                                                              # 评估与统计指标结果 JSON
    error: Mapped[str | None] = mapped_column(Text)                                                                     # 异常或错误堆栈文本
    host: Mapped[str | None] = mapped_column(String)                                                                    # 执行主机/节点环境信息
    started_at: Mapped[str] = mapped_column(String, nullable=False)                                                    # 开始时间 (ISO 8601)
    ended_at: Mapped[str | None] = mapped_column(String)                                                               # 结束时间 (ISO 8601)
    duration_s: Mapped[float | None] = mapped_column(Float)                                                             # 运行总耗时 (秒)
    created_at: Mapped[str] = mapped_column(String, nullable=False)                                                    # 创建时间 (ISO 8601)


class ReviewSession(Base):
    __tablename__ = "review_sessions"
    __table_args__ = (
        ForeignKeyConstraint(["tiff_id", "phase_id"], ["tiffs.tiff_id", "tiffs.phase_id"], ondelete="CASCADE"),
    )

    session_id: Mapped[str] = mapped_column(String, primary_key=True)                                            # 人工复核会话唯一 ID
    phase_id: Mapped[str] = mapped_column(String, nullable=False)                                                # 关联时相 ID
    tiff_id: Mapped[str] = mapped_column(String, nullable=False)                                                 # 关联 TIFF 影像 ID
    tract_phase_pk: Mapped[str] = mapped_column(ForeignKey("tract_phases.tract_phase_pk", ondelete="CASCADE"))  # 所属地块时相外键
    mode: Mapped[str] = mapped_column(String, nullable=False)                                                    # 复核模式 (如 active_run / compare)
    base_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.run_id", ondelete="SET NULL"))              # 基准 Run ID 外键
    expected_active_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.run_id", ondelete="SET NULL"))  # 期望的 Active Run ID 外键
    status: Mapped[str] = mapped_column(String, default="active")                                                # 会话状态 (active / published / discarded)
    revision: Mapped[int] = mapped_column(Integer, default=0)                                                    # 草稿修订版本号
    draft_path: Mapped[str] = mapped_column(Text, nullable=False)                                                # 复核草稿 GeoJSON 文件存储路径
    summary_json: Mapped[str | None] = mapped_column(Text)                                                     # 复核变更统计与摘要信息 JSON
    published_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.run_id", ondelete="SET NULL"))        # 发布产出的新 Run ID 外键
    created_at: Mapped[str] = mapped_column(String, nullable=False)                                                # 创建时间 (ISO 8601)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)                                                # 更新时间 (ISO 8601)


class TreeIndividual(Base):
    __tablename__ = "tree_individuals"

    individual_id: Mapped[str] = mapped_column(String, primary_key=True)       # 8 位哈希全球唯一单木个体 ID
    first_seen_phase_id: Mapped[str | None] = mapped_column(String)            # 首次出现的时相 ID
    last_seen_phase_id: Mapped[str | None] = mapped_column(String)             # 最近一次出现的时相 ID
    global_status: Mapped[str] = mapped_column(String, default="alive")        # 长期生存状态 (alive / missing / removed / unknown)
    tracking_confidence: Mapped[float | None] = mapped_column(Float)           # 跨时相追踪匹配置信度
    growth_json: Mapped[str | None] = mapped_column(Text)                      # 跨时相生长轨迹与历史变化 JSON
    created_at: Mapped[str] = mapped_column(String, nullable=False)            # 创建时间 (ISO 8601)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)            # 更新时间 (ISO 8601)

    observations: Mapped[list["TreeObservation"]] = relationship(back_populates="individual")


class TreeObservation(Base):
    __tablename__ = "tree_observations"
    __table_args__ = (
        ForeignKeyConstraint(["tiff_id", "phase_id"], ["tiffs.tiff_id", "tiffs.phase_id"], ondelete="SET NULL"),
    )

    observation_id: Mapped[str] = mapped_column(String, primary_key=True)                                              # 观测记录唯一 ID
    individual_id: Mapped[str | None] = mapped_column(ForeignKey("tree_individuals.individual_id", ondelete="SET NULL"))  # 匹配到的单木个体外键
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id", ondelete="CASCADE"))                                  # 产生该观测的推理 Run 外键
    tract_phase_pk: Mapped[str] = mapped_column(ForeignKey("tract_phases.tract_phase_pk", ondelete="CASCADE"))          # 所属地块时相外键
    tiff_id: Mapped[str | None] = mapped_column(String)                                                                 # 来源 TIFF 影像 ID
    phase_id: Mapped[str | None] = mapped_column(String)                                                                # 来源时相 ID
    species: Mapped[str | None] = mapped_column(String)                                                                 # 树种类别名称
    confidence: Mapped[float | None] = mapped_column(Float)                                                             # 检测/分类置信度
    center_geom: Mapped[str | None] = mapped_column(Text)                                                              # 树冠中心点地理坐标 (GeoJSON/WKT)
    crown_geom: Mapped[str | None] = mapped_column(Text)                                                               # 树冠多边形轮廓 (GeoJSON/WKT)
    box_px: Mapped[str | None] = mapped_column(Text)                                                                    # 全图像素检测框 JSON ([x1, y1, x2, y2])
    box_px_sub: Mapped[str | None] = mapped_column(Text)                                                                # 来源瓦片切片内像素检测框 JSON ([x1, y1, x2, y2])
    box_geo: Mapped[str | None] = mapped_column(Text)                                                                   # 地理坐标系下的检测框 JSON
    crown_width_px: Mapped[float | None] = mapped_column(Float)                                                        # 树冠像素宽度 (PX)
    crown_height_px: Mapped[float | None] = mapped_column(Float)                                                       # 树冠像素高度 (PX)
    crown_width_geo: Mapped[float | None] = mapped_column(Float)                                                       # 树冠地理宽度 (米)
    crown_height_geo: Mapped[float | None] = mapped_column(Float)                                                      # 树冠地理高度 (米)
    crown_area_px: Mapped[float | None] = mapped_column(Float)                                                         # 树冠像素面积 (PX²)
    crown_area_geo_est: Mapped[float | None] = mapped_column(Float)                                                    # 树冠地理估算面积 (m²，默认冠幅宽高相乘)
    crown_area_geo_real: Mapped[float | None] = mapped_column(Float)                                                   # 树冠地理精确面积 (m²，由多边形/Mask精确计算)
    height: Mapped[float | None] = mapped_column(Float)                                                                # 树高 (米)
    height_source: Mapped[str | None] = mapped_column(String)                                                          # 树高计算来源 (chm / dsm_dem / manual / unknown)
    source: Mapped[str] = mapped_column(String, default="infer")                                                       # 框来源 (infer: 模型离线批处理 / manual: review人工手绘 / review: 开放世界prompt)
    crown_volume_geo_est: Mapped[float | None] = mapped_column(Float)                                                   # 树冠估算体积 (m³)
    crown_volume_geo_real: Mapped[float | None] = mapped_column(Float)                                                  # 树冠真实/精确体积 (m³)
    source_subimage_path: Mapped[str | None] = mapped_column(Text)                                                      # 来源单木切片小图相对/绝对路径
    slice_size: Mapped[int | None] = mapped_column(Integer)                                                             # 检测该单木时的图像切割尺寸 (PX)
    created_at: Mapped[str] = mapped_column(String, nullable=False)                                                    # 创建时间 (ISO 8601)

    individual: Mapped[TreeIndividual | None] = relationship(back_populates="observations")
