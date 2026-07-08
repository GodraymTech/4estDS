"""SQLAlchemy 2.0 ORM mappings for the tract-phase-TIFF model."""
from __future__ import annotations

from sqlalchemy import Float, ForeignKey, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Tract(Base):
    __tablename__ = "tracts"
    __table_args__ = (UniqueConstraint("region_id", "tract_id"),)

    tract_pk: Mapped[str] = mapped_column(String, primary_key=True)
    region_id: Mapped[str] = mapped_column(String, nullable=False)
    tract_id: Mapped[str] = mapped_column(String, nullable=False)
    boundary_geom: Mapped[str | None] = mapped_column(Text)
    boundary_source: Mapped[str] = mapped_column(String, default="unset")
    coverage_status: Mapped[str] = mapped_column(String, default="none")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)

    phases: Mapped[list["TractPhase"]] = relationship(back_populates="tract")


class TractPhase(Base):
    __tablename__ = "tract_phases"
    __table_args__ = (UniqueConstraint("tract_pk", "phase_id"),)

    tract_phase_pk: Mapped[str] = mapped_column(String, primary_key=True)
    tract_pk: Mapped[str] = mapped_column(ForeignKey("tracts.tract_pk", ondelete="CASCADE"))
    region_id: Mapped[str] = mapped_column(String, nullable=False)
    tract_id: Mapped[str] = mapped_column(String, nullable=False)
    phase_id: Mapped[str] = mapped_column(String, nullable=False)
    boundary_geom: Mapped[str | None] = mapped_column(Text)
    coverage_status: Mapped[str] = mapped_column(String, default="none")
    active_run_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)

    tract: Mapped[Tract] = relationship(back_populates="phases")
    tiffs: Mapped[list["Tiff"]] = relationship(back_populates="tract_phase")


class Tiff(Base):
    __tablename__ = "tiffs"

    tiff_id: Mapped[str] = mapped_column(String, primary_key=True)
    phase_id: Mapped[str] = mapped_column(String, primary_key=True)
    tract_phase_pk: Mapped[str] = mapped_column(ForeignKey("tract_phases.tract_phase_pk", ondelete="CASCADE"))
    file_name: Mapped[str | None] = mapped_column(Text)
    path_versions: Mapped[str] = mapped_column(Text, default="{}")
    multisource_path_versions: Mapped[str] = mapped_column(Text, default="{}")
    footprint_geom: Mapped[str] = mapped_column(Text, nullable=False)
    footprint_bbox: Mapped[str | None] = mapped_column(Text)
    corner_hash_input: Mapped[str] = mapped_column(Text, nullable=False)
    crs_epsg: Mapped[int | None] = mapped_column(Integer)
    crs_wkt: Mapped[str | None] = mapped_column(Text)
    geotransform: Mapped[str | None] = mapped_column(Text)
    pixel_width: Mapped[int | None] = mapped_column(Integer)
    pixel_height: Mapped[int | None] = mapped_column(Integer)
    gsd: Mapped[float | None] = mapped_column(Float)
    geo_area: Mapped[float | None] = mapped_column(Float)
    area_unit: Mapped[str | None] = mapped_column(String)
    band_count: Mapped[int | None] = mapped_column(Integer)
    dtype: Mapped[str | None] = mapped_column(String)
    nodata: Mapped[float | None] = mapped_column(Float)
    inference_status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)

    tract_phase: Mapped[TractPhase] = relationship(back_populates="tiffs")


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        ForeignKeyConstraint(["tiff_id", "phase_id"], ["tiffs.tiff_id", "tiffs.phase_id"], ondelete="SET NULL"),
    )

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    parent_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.run_id", ondelete="SET NULL"))
    tag: Mapped[str | None] = mapped_column(String)
    tract_phase_pk: Mapped[str | None] = mapped_column(ForeignKey("tract_phases.tract_phase_pk", ondelete="SET NULL"))
    tiff_id: Mapped[str | None] = mapped_column(String)
    phase_id: Mapped[str] = mapped_column(String, nullable=False)
    task_type: Mapped[str] = mapped_column(String, nullable=False)
    model_arch: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="running")
    slice_size: Mapped[int | None] = mapped_column(Integer)
    input_path: Mapped[str | None] = mapped_column(Text)
    tiles_dir: Mapped[str | None] = mapped_column(Text)
    input_json: Mapped[str | None] = mapped_column(Text)
    params_json: Mapped[str | None] = mapped_column(Text)
    metrics_json: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    host: Mapped[str | None] = mapped_column(String)
    started_at: Mapped[str] = mapped_column(String, nullable=False)
    ended_at: Mapped[str | None] = mapped_column(String)
    duration_s: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class TreeIndividual(Base):
    __tablename__ = "tree_individuals"

    individual_id: Mapped[str] = mapped_column(String, primary_key=True)
    first_seen_phase_id: Mapped[str | None] = mapped_column(String)
    last_seen_phase_id: Mapped[str | None] = mapped_column(String)
    global_status: Mapped[str] = mapped_column(String, default="alive")
    tracking_confidence: Mapped[float | None] = mapped_column(Float)
    growth_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)

    observations: Mapped[list["TreeObservation"]] = relationship(back_populates="individual")


class TreeObservation(Base):
    __tablename__ = "tree_observations"
    __table_args__ = (
        ForeignKeyConstraint(["tiff_id", "phase_id"], ["tiffs.tiff_id", "tiffs.phase_id"], ondelete="SET NULL"),
    )

    observation_id: Mapped[str] = mapped_column(String, primary_key=True)
    individual_id: Mapped[str | None] = mapped_column(ForeignKey("tree_individuals.individual_id", ondelete="SET NULL"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id", ondelete="CASCADE"))
    tract_phase_pk: Mapped[str] = mapped_column(ForeignKey("tract_phases.tract_phase_pk", ondelete="CASCADE"))
    tiff_id: Mapped[str | None] = mapped_column(String)
    phase_id: Mapped[str | None] = mapped_column(String)
    species: Mapped[str | None] = mapped_column(String)
    confidence: Mapped[float | None] = mapped_column(Float)
    center_geom: Mapped[str | None] = mapped_column(Text)
    crown_geom: Mapped[str | None] = mapped_column(Text)
    box_px: Mapped[str | None] = mapped_column(Text)
    box_px_sub: Mapped[str | None] = mapped_column(Text)
    box_geo: Mapped[str | None] = mapped_column(Text)
    crown_width_px: Mapped[float | None] = mapped_column(Float)
    crown_height_px: Mapped[float | None] = mapped_column(Float)
    crown_width_geo: Mapped[float | None] = mapped_column(Float)
    crown_height_geo: Mapped[float | None] = mapped_column(Float)
    crown_area_px: Mapped[float | None] = mapped_column(Float)
    crown_area_geo_est: Mapped[float | None] = mapped_column(Float)
    crown_area_geo_real: Mapped[float | None] = mapped_column(Float)
    height: Mapped[float | None] = mapped_column(Float)
    height_source: Mapped[str | None] = mapped_column(String)
    crown_volume_geo_est: Mapped[float | None] = mapped_column(Float)
    crown_volume_geo_real: Mapped[float | None] = mapped_column(Float)
    source_subimage_path: Mapped[str | None] = mapped_column(Text)
    slice_size: Mapped[int | None] = mapped_column(Integer)
    geom_point: Mapped[str | None] = mapped_column(Text)
    geom_crown: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String, nullable=False)

    individual: Mapped[TreeIndividual | None] = relationship(back_populates="observations")
