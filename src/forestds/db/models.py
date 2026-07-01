"""SQLAlchemy 2.0 ORM 映射(三层单木模型)。

仅在本地安装 ``uv sync --extra db`` 后可用。未安装 SQLAlchemy 时,
``import`` 会报错——这是预期的;沙盒/最小环境请用 ``db.schema`` 的标准库路径。
Geometry 在 SQLite 阶段以文本(WKT/GeoJSON)存储,迁移 PostGIS 后换为 GeoAlchemy2。

TODO(阶段二): 接入 Alembic 迁移;PostGIS 下将 *_geom 列换为 Geometry 类型。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class RunLog(Base):
    __tablename__ = "run_logs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    parent_run_id: Mapped[str | None] = mapped_column(String)
    tag: Mapped[str | None] = mapped_column(String)
    task_type: Mapped[str] = mapped_column(String, nullable=False)
    model_arch: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="running")
    started_at: Mapped[str] = mapped_column(String, nullable=False)
    ended_at: Mapped[str | None] = mapped_column(String)
    duration_s: Mapped[float | None] = mapped_column(Float)
    input_path: Mapped[str | None] = mapped_column(Text)
    tiles_dir: Mapped[str | None] = mapped_column(Text)
    params_json: Mapped[str | None] = mapped_column(Text)
    metrics_json: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    host: Mapped[str | None] = mapped_column(String)


class TreeIndividual(Base):
    __tablename__ = "tree_individuals"

    individual_id: Mapped[str] = mapped_column(String, primary_key=True)
    location_cluster: Mapped[str | None] = mapped_column(String)
    first_seen: Mapped[str | None] = mapped_column(String)
    last_seen: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="alive")
    growth_json: Mapped[str | None] = mapped_column(Text)

    canonicals: Mapped[list["TractTree"]] = relationship(back_populates="individual")


class Tract(Base):
    __tablename__ = "tracts"
    __table_args__ = (UniqueConstraint("acquisition_time", "location"),)

    tract_id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_ref: Mapped[str | None] = mapped_column(String)
    name: Mapped[str | None] = mapped_column(String)
    acquisition_time: Mapped[str] = mapped_column(String, nullable=False)  # YYYYMM
    location: Mapped[str] = mapped_column(String, nullable=False)
    pixel_w: Mapped[int | None] = mapped_column(Integer)
    pixel_h: Mapped[int | None] = mapped_column(Integer)
    gsd: Mapped[float | None] = mapped_column(Float)
    geo_area: Mapped[float | None] = mapped_column(Float)
    area_unit: Mapped[str | None] = mapped_column(String)
    crs_epsg: Mapped[int | None] = mapped_column(Integer)
    crs_wkt: Mapped[str | None] = mapped_column(Text)
    geotransform: Mapped[str | None] = mapped_column(Text)
    bounds_bbox: Mapped[str | None] = mapped_column(Text)
    nodata: Mapped[float | None] = mapped_column(Float)
    band_count: Mapped[int | None] = mapped_column(Integer)
    dtype: Mapped[str | None] = mapped_column(String)
    footprint_geom: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="registered")
    notes: Mapped[str | None] = mapped_column(Text)

    sources: Mapped[list["TractSource"]] = relationship(back_populates="tract")


class TractSource(Base):
    __tablename__ = "tract_sources"

    source_id: Mapped[str] = mapped_column(String, primary_key=True)
    tract_id: Mapped[str] = mapped_column(ForeignKey("tracts.tract_id", ondelete="CASCADE"))
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    meta_json: Mapped[str | None] = mapped_column(Text)

    tract: Mapped[Tract] = relationship(back_populates="sources")


class TreeObservation(Base):
    __tablename__ = "tree_observations"

    obs_id: Mapped[str] = mapped_column(String, primary_key=True)
    tract_id: Mapped[str] = mapped_column(ForeignKey("tracts.tract_id", ondelete="CASCADE"))
    run_id: Mapped[str] = mapped_column(ForeignKey("run_logs.run_id", ondelete="CASCADE"))
    species: Mapped[str | None] = mapped_column(String)
    confidence: Mapped[float | None] = mapped_column(Float)
    box_px_sub: Mapped[str | None] = mapped_column(Text)
    box_px_full: Mapped[str | None] = mapped_column(Text)
    box_geo: Mapped[str | None] = mapped_column(Text)
    crown_w_px: Mapped[float | None] = mapped_column(Float)
    crown_h_px: Mapped[float | None] = mapped_column(Float)
    crown_w_geo: Mapped[float | None] = mapped_column(Float)
    crown_h_geo: Mapped[float | None] = mapped_column(Float)
    height: Mapped[float | None] = mapped_column(Float)
    height_source: Mapped[str | None] = mapped_column(String)
    crown_area_px_est: Mapped[float | None] = mapped_column(Float)
    crown_area_px_real: Mapped[float | None] = mapped_column(Float)
    crown_area_geo_est: Mapped[float | None] = mapped_column(Float)
    crown_area_geo_real: Mapped[float | None] = mapped_column(Float)
    crown_volume_geo_est: Mapped[float | None] = mapped_column(Float)
    crown_volume_geo_real: Mapped[float | None] = mapped_column(Float)
    center_geo: Mapped[str | None] = mapped_column(Text)
    source_subimage_path: Mapped[str | None] = mapped_column(Text)
    slice_size: Mapped[int | None] = mapped_column(Integer)
    geom_point: Mapped[str | None] = mapped_column(Text)
    geom_crown: Mapped[str | None] = mapped_column(Text)


class TractTree(Base):
    __tablename__ = "tract_trees"

    canonical_id: Mapped[str] = mapped_column(String, primary_key=True)
    tract_id: Mapped[str] = mapped_column(ForeignKey("tracts.tract_id", ondelete="CASCADE"))
    individual_id: Mapped[str | None] = mapped_column(
        ForeignKey("tree_individuals.individual_id", ondelete="SET NULL")
    )
    species: Mapped[str | None] = mapped_column(String)
    confidence: Mapped[float | None] = mapped_column(Float)
    geom_point: Mapped[str | None] = mapped_column(Text)
    geom_crown: Mapped[str | None] = mapped_column(Text)
    height: Mapped[float | None] = mapped_column(Float)
    crown_area_geo_est: Mapped[float | None] = mapped_column(Float)
    crown_area_geo_real: Mapped[float | None] = mapped_column(Float)
    crown_volume_geo_est: Mapped[float | None] = mapped_column(Float)
    crown_volume_geo_real: Mapped[float | None] = mapped_column(Float)
    chosen_obs_id: Mapped[str | None] = mapped_column(
        ForeignKey("tree_observations.obs_id", ondelete="SET NULL")
    )
    active_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("run_logs.run_id", ondelete="SET NULL")
    )

    individual: Mapped[TreeIndividual | None] = relationship(back_populates="canonicals")
