"""影像资产台账端点。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from ...db import writer
from ...db.schema import init_db, resolve_db_path
from ...geo.admin import UNKNOWN_COUNTY, UNKNOWN_TOWN, inspect_image_center, region_id as make_region_id, split_region_id
from ...utils.input_inspect import inspect_input_path
from ...utils.input_inspect import normalize_user_path
from ..deps import get_db_url
from .geo import AmapConfigError, AmapServiceError, reverse_admin
from ..schemas import (
    AssetCogConvertOut,
    AssetCogConvertRequest,
    AssetInspectOut,
    AssetInspectRequest,
    AssetPatch,
    AssetRow,
    AssetTiffCreate,
)

router = APIRouter(prefix="/assets", tags=["assets"])


def _connect(url: str | None) -> sqlite3.Connection:
    init_db(url)
    conn = sqlite3.connect(resolve_db_path(url))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _loads(raw: str | None, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _latest_path(raw: str | None) -> str | None:
    data = _loads(raw, {})
    if not isinstance(data, dict) or not data:
        return None
    key = sorted(str(k) for k in data.keys())[-1]
    value = data.get(key)
    return str(value) if value else None


def _image_stem(path_or_name: str | None) -> str | None:
    if not path_or_name:
        return None
    return Path(path_or_name).stem


def _display_user_path(path: str | Path | None) -> str | None:
    if path is None:
        return None
    text = str(path)
    if text.startswith("/mnt/") and len(text) > 7 and text[6] == "/":
        drive = text[5].upper()
        rest = text[7:].replace("/", "\\")
        return f"{drive}:\\{rest}"
    return text


def _status(row: sqlite3.Row, count: int) -> str:
    run_status = row["run_status"]
    if run_status == "succeeded" or row["inference_status"] == "inferred" or count > 0:
        return "已检测"
    if run_status == "running":
        return "检测中"
    if run_status == "failed":
        return "检测失败"
    return "未检测"


@router.get("", response_model=list[AssetRow], summary="影像资产台账")
def list_assets(db_url: str | None = Depends(get_db_url)) -> list[AssetRow]:
    conn = _connect(db_url)
    try:
        rows = conn.execute(
            "SELECT tr.tract_pk, tr.region_id, tr.city, tr.county, tr.town, tr.tract_id, "
            "tp.tract_phase_pk, tp.phase_id, tf.tiff_id, tf.file_name, tf.path_versions, "
            "tf.tiff_type, tf.geo_area, tf.area_unit, tf.inference_status, r.run_id, r.status AS run_status, "
            "COALESCE(r.ended_at, r.started_at) AS detected_at, "
            "(SELECT COUNT(*) FROM tree_observations o WHERE o.tiff_id=tf.tiff_id AND o.phase_id=tf.phase_id) AS observation_count "
            "FROM tract_phases tp "
            "JOIN tracts tr ON tr.tract_pk=tp.tract_pk "
            "JOIN tiffs tf ON tf.tract_phase_pk=tp.tract_phase_pk "
            "LEFT JOIN runs r ON r.rowid=("
            "  SELECT r2.rowid FROM runs r2 "
            "  WHERE r2.tiff_id=tf.tiff_id AND r2.phase_id=tf.phase_id "
            "  ORDER BY r2.started_at DESC LIMIT 1"
            ") "
            "ORDER BY tr.city, tr.county, tr.tract_id, tp.phase_id DESC, tf.file_name"
        ).fetchall()
    finally:
        conn.close()

    out: list[AssetRow] = []
    for row in rows:
        count = int(row["observation_count"] or 0)
        city = row["city"]
        county = row["county"]
        if (not city or not county) and row["region_id"]:
            city, county = split_region_id(row["region_id"])
        out.append(
            AssetRow(
                city=city,
                county=county,
                town=row["town"],
                region_id=row["region_id"],
                tract_pk=row["tract_pk"],
                tract_id=row["tract_id"],
                tract_phase_pk=row["tract_phase_pk"],
                phase_id=row["phase_id"],
                tiff_id=row["tiff_id"],
                image_name=row["file_name"],
                source_path=_latest_path(row["path_versions"]),
                tiff_type=row["tiff_type"],
                run_id=row["run_id"],
                status=_status(row, count),
                geo_area=row["geo_area"],
                area_unit=row["area_unit"],
                observation_count=count,
                detected_at=row["detected_at"],
            )
        )
    return out


@router.post("/inspect-image", response_model=AssetInspectOut, summary="检查影像行政区划与时间属性")
def inspect_asset_image(body: AssetInspectRequest) -> AssetInspectOut:
    lng = body.lng
    lat = body.lat
    normalized_path: str | None = None
    image = None
    inspect_error: str | None = None
    exists = False
    tiff_type: str | None = None
    tiff_type_label: str | None = None
    suggested_cog_path: str | None = None
    if body.input_path:
        normalized_path = normalize_user_path(body.input_path)
        try:
            kind, path, images = inspect_input_path(body.input_path)
        except FileNotFoundError as exc:
            inspect_error = str(exc)
        except ValueError as exc:
            inspect_error = str(exc)
        else:
            exists = True
            if kind != "file" or not images:
                inspect_error = "请录入单张 TIFF/影像文件"
            else:
                image = images[0]
                normalized_path = str(path)
                lng, lat = inspect_image_center(normalized_path)
                if path.suffix.lower() in {".tif", ".tiff"}:
                    from ...preprocess.cog import (
                        TIFF_FORMAT_LABELS,
                        TIFF_INVALID,
                        inspect_tiff_error,
                        inspect_tiff_format,
                        is_tiff_tile_ready,
                    )

                    tiff_type = inspect_tiff_format(path)
                    tiff_type_label = TIFF_FORMAT_LABELS.get(tiff_type, tiff_type)
                    if tiff_type == TIFF_INVALID:
                        inspect_error = inspect_tiff_error(path) or "TIFF 无法被 GDAL/rasterio 读取"
                    if tiff_type != TIFF_INVALID and not is_tiff_tile_ready(tiff_type):
                        suggested_cog_path = str(path.parent / f"{path.stem}_cog.tif")

    geo_error: str | None = None
    try:
        admin = reverse_admin(lng, lat)
        city, county, town = admin.city, admin.county, admin.town
    except (AmapConfigError, AmapServiceError) as exc:
        city, county, town = "未知市", UNKNOWN_COUNTY, UNKNOWN_TOWN
        geo_error = str(exc)
    fallback_name = Path(normalized_path).name if normalized_path else None
    fallback_stem = _image_stem(fallback_name)
    return AssetInspectOut(
        input_path=body.input_path,
        normalized_path=normalized_path,
        exists=exists,
        inspect_error=inspect_error,
        image_name=fallback_stem,
        suggested_tract_id=image.stem if image else fallback_stem,
        suggested_phase_id=image.phase_id if image else None,
        city=city,
        county=county,
        town=town,
        region_id=make_region_id(city, county),
        lng=lng,
        lat=lat,
        width=image.width if image else None,
        height=image.height if image else None,
        crs_epsg=image.crs_epsg if image else None,
        tiff_type=tiff_type,
        tiff_type_label=tiff_type_label,
        cog_required=bool(tiff_type and suggested_cog_path),
        suggested_cog_path=suggested_cog_path,
        suggested_cog_display_path=_display_user_path(suggested_cog_path),
        geo_error=geo_error,
    )


@router.post("/convert-cog", response_model=AssetCogConvertOut, summary="将单个 TIFF 转为严格 COG")
def convert_asset_cog(body: AssetCogConvertRequest) -> AssetCogConvertOut:
    from ...preprocess.cog import TIFF_COG, TIFF_FORMAT_LABELS, inspect_tiff_format, prepared_cog_path

    normalized = normalize_user_path(body.input_path)
    path = Path(normalized).expanduser()
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"TIFF 不存在: {path}")
    if path.suffix.lower() not in {".tif", ".tiff"}:
        raise HTTPException(status_code=415, detail="只支持 tif/tiff 单文件转换")

    source_type = inspect_tiff_format(path)
    cog_path, prepared_type = prepared_cog_path(path, force=True)
    if prepared_type != TIFF_COG:
        raise HTTPException(status_code=500, detail=f"COG 转换失败: {prepared_type}")

    return AssetCogConvertOut(
        input_path=body.input_path,
        source_path=str(path),
        source_display_path=_display_user_path(path) or str(path),
        cog_path=str(cog_path),
        cog_display_path=_display_user_path(cog_path) or str(cog_path),
        tiff_type=prepared_type,
        tiff_type_label=TIFF_FORMAT_LABELS[prepared_type],
        converted=str(path.resolve()) != str(cog_path.resolve()) or source_type != TIFF_COG,
    )


@router.post("/tiffs", response_model=list[AssetRow], summary="手动录入 TIFF")
def create_tiff_asset(body: AssetTiffCreate, db_url: str | None = Depends(get_db_url)) -> list[AssetRow]:
    inspected = inspect_asset_image(AssetInspectRequest(input_path=body.input_path))
    if inspected.inspect_error:
        raise HTTPException(status_code=400, detail=inspected.inspect_error)
    tract_id = body.tract_id or inspected.suggested_tract_id or Path(body.input_path).stem
    phase_id = body.phase_id or inspected.suggested_phase_id or "00000000"
    city = body.city or inspected.city
    county = body.county or inspected.county
    town = body.town or inspected.town
    image_path = inspected.normalized_path or body.input_path
    writer.ensure_tract(
        phase_id,
        tract_id,
        url=db_url,
        city=city,
        county=county,
        town=town,
        image_path=image_path,
    )
    image_name = body.image_name or inspected.image_name or _image_stem(image_path)
    if image_name:
        conn = _connect(db_url)
        try:
            conn.execute(
                "UPDATE tiffs SET file_name=?, updated_at=datetime('now') "
                "WHERE phase_id=? AND (path_versions LIKE ? OR path_versions LIKE ?)",
                (image_name, phase_id, f"%{image_path}%", f"%{body.input_path}%"),
            )
            conn.commit()
        finally:
            conn.close()
    return list_assets(db_url)


@router.patch("/tracts/{tract_pk}", response_model=list[AssetRow], summary="修改地块")
def patch_tract(tract_pk: str, body: AssetPatch, db_url: str | None = Depends(get_db_url)) -> list[AssetRow]:
    conn = _connect(db_url)
    try:
        row = conn.execute("SELECT * FROM tracts WHERE tract_pk=?", (tract_pk,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="地块不存在")
        city = body.city or row["city"]
        county = body.county or row["county"]
        town = body.town or row["town"]
        tract_id = body.tract_id or row["tract_id"]
        region_id = make_region_id(city, county)
        conn.execute(
            "UPDATE tracts SET region_id=?, city=?, county=?, town=?, tract_id=?, updated_at=datetime('now') WHERE tract_pk=?",
            (region_id, city, county, town, tract_id, tract_pk),
        )
        conn.execute(
            "UPDATE tract_phases SET region_id=?, tract_id=?, updated_at=datetime('now') WHERE tract_pk=?",
            (region_id, tract_id, tract_pk),
        )
        conn.commit()
    finally:
        conn.close()
    return list_assets(db_url)


@router.patch("/tiffs/{phase_id}/{tiff_id}", response_model=list[AssetRow], summary="修改 TIFF")
def patch_tiff(
    phase_id: str,
    tiff_id: str,
    body: AssetPatch,
    db_url: str | None = Depends(get_db_url),
) -> list[AssetRow]:
    conn = _connect(db_url)
    try:
        row = conn.execute("SELECT * FROM tiffs WHERE phase_id=? AND tiff_id=?", (phase_id, tiff_id)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="TIFF 不存在")
        path_versions = row["path_versions"]
        tiff_type = body.tiff_type
        if body.new_path:
            data = _loads(path_versions, {})
            data[Path(body.new_path).name + ":" + str(len(data) + 1)] = body.new_path
            path_versions = _dump(data)
            if not tiff_type:
                from ...preprocess.cog import inspect_tiff_format

                tiff_type = inspect_tiff_format(normalize_user_path(body.new_path))
        conn.execute(
            "UPDATE tiffs SET file_name=COALESCE(?, file_name), path_versions=?, "
            "tiff_type=COALESCE(?, tiff_type), updated_at=datetime('now') "
            "WHERE phase_id=? AND tiff_id=?",
            (body.image_name, path_versions, tiff_type, phase_id, tiff_id),
        )
        conn.commit()
    finally:
        conn.close()
    return list_assets(db_url)


@router.delete("/tiffs/{phase_id}/{tiff_id}", response_model=list[AssetRow], summary="删除 TIFF")
def delete_tiff(
    phase_id: str,
    tiff_id: str,
    force: bool = Query(False),
    db_url: str | None = Depends(get_db_url),
) -> list[AssetRow]:
    conn = _connect(db_url)
    try:
        row = conn.execute(
            "SELECT tract_phase_pk FROM tiffs WHERE phase_id=? AND tiff_id=?",
            (phase_id, tiff_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="TIFF 不存在")
        tract_phase_pk = row["tract_phase_pk"]
        tract_row = conn.execute(
            "SELECT tract_pk FROM tract_phases WHERE tract_phase_pk=?",
            (tract_phase_pk,),
        ).fetchone()
        tract_pk = tract_row["tract_pk"] if tract_row else None
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM tree_observations WHERE phase_id=? AND tiff_id=?",
            (phase_id, tiff_id),
        ).fetchone()["c"]
        if int(count) > 0 and not force:
            raise HTTPException(status_code=409, detail=f"该 TIFF 已检测，删除将移除 {count} 条观测和相关运行记录")
        conn.execute("DELETE FROM tree_observations WHERE phase_id=? AND tiff_id=?", (phase_id, tiff_id))
        conn.execute("DELETE FROM runs WHERE phase_id=? AND tiff_id=?", (phase_id, tiff_id))
        conn.execute("DELETE FROM tiffs WHERE phase_id=? AND tiff_id=?", (phase_id, tiff_id))
        phase_children = conn.execute(
            "SELECT COUNT(*) AS c FROM tiffs WHERE tract_phase_pk=?",
            (tract_phase_pk,),
        ).fetchone()["c"]
        if int(phase_children) == 0:
            conn.execute("DELETE FROM tract_phases WHERE tract_phase_pk=?", (tract_phase_pk,))
        if tract_pk:
            tract_children = conn.execute(
                "SELECT COUNT(*) AS c FROM tract_phases WHERE tract_pk=?",
                (tract_pk,),
            ).fetchone()["c"]
            if int(tract_children) == 0:
                conn.execute("DELETE FROM tracts WHERE tract_pk=?", (tract_pk,))
        conn.commit()
    finally:
        conn.close()
    return list_assets(db_url)
