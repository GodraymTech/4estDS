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
    AssetDeletePreview,
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


@router.get("", response_model=list[AssetRow], summary="影像资产台账")
def list_assets(db_url: str | None = Depends(get_db_url)) -> list[AssetRow]:
    from ...db import reader

    out: list[AssetRow] = []
    for row in reader.list_tiffs(url=db_url):
        city = row.get("city")
        county = row.get("county")
        if (not city or not county) and row.get("region_id"):
            city, county = split_region_id(row["region_id"])
        out.append(
            AssetRow(
                city=city,
                county=county,
                town=row.get("town"),
                region_id=row.get("region_id"),
                tract_pk=row.get("tract_pk"),
                tract_id=row.get("tract_id"),
                tract_phase_pk=row.get("tract_phase_pk"),
                phase_id=row.get("phase_id"),
                tiff_id=row.get("tiff_id"),
                image_name=_image_stem(row.get("file_name")),
                source_path=row.get("source_path"),
                tiff_type=row.get("tiff_type"),
                active_run_id=row.get("active_run_id"),
                run_id=row.get("run_id"),
                run_count=int(row.get("run_count") or 0),
                run_status_counts=row.get("run_status_counts") or {},
                active_run_status=row.get("active_run_status"),
                status=row.get("status") or "未检测",
                geo_area=row.get("geo_area"),
                area_unit=row.get("area_unit"),
                observation_count=int(row.get("observation_count") or 0),
                detected_at=row.get("detected_at"),
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
    image_name = _image_stem(body.image_name or inspected.image_name or image_path)
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
    import re

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
        image_name = _image_stem(body.image_name) if body.image_name else None

        new_phase_id = phase_id
        if body.phase_id:
            new_phase_id = writer._normalize_phase_id(body.phase_id)
            if not re.match(r"^\d{8}$", new_phase_id):
                raise HTTPException(status_code=400, detail="时相格式无效，须为 8 位数字（如 20260711）")

        if new_phase_id != phase_id:
            old_tract_phase_pk = row["tract_phase_pk"]
            tp = conn.execute("SELECT * FROM tract_phases WHERE tract_phase_pk=?", (old_tract_phase_pk,)).fetchone()
            if not tp:
                raise HTTPException(status_code=404, detail="关联的地块时相信息不存在")

            new_tract_phase_pk = writer._safe_pk("phase", tp["tract_pk"], new_phase_id)

            conn.execute("PRAGMA foreign_keys = OFF")
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO tract_phases (tract_phase_pk, tract_pk, region_id, tract_id, phase_id, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, datetime('now'))",
                    (new_tract_phase_pk, tp["tract_pk"], tp["region_id"], tp["tract_id"], new_phase_id),
                )
                conn.execute(
                    "UPDATE runs SET phase_id=?, tract_phase_pk=? WHERE phase_id=? AND tiff_id=?",
                    (new_phase_id, new_tract_phase_pk, phase_id, tiff_id),
                )
                conn.execute(
                    "UPDATE tree_observations SET phase_id=?, tract_phase_pk=? WHERE phase_id=? AND tiff_id=?",
                    (new_phase_id, new_tract_phase_pk, phase_id, tiff_id),
                )
                conn.execute(
                    "UPDATE tiffs SET phase_id=?, tract_phase_pk=?, file_name=COALESCE(?, file_name), "
                    "path_versions=?, tiff_type=COALESCE(?, tiff_type), updated_at=datetime('now') "
                    "WHERE phase_id=? AND tiff_id=?",
                    (new_phase_id, new_tract_phase_pk, image_name, path_versions, tiff_type, phase_id, tiff_id),
                )
                # Cleanup empty tract_phases
                c = conn.execute(
                    "SELECT COUNT(*) AS c FROM tiffs WHERE tract_phase_pk=?",
                    (old_tract_phase_pk,),
                ).fetchone()["c"]
                if c == 0:
                    conn.execute("DELETE FROM tract_phases WHERE tract_phase_pk=?", (old_tract_phase_pk,))
                conn.commit()
            except sqlite3.IntegrityError as e:
                conn.rollback()
                if "UNIQUE constraint failed" in str(e):
                    raise HTTPException(status_code=409, detail="修改后的时相下已存在该 TIFF 资产")
                raise HTTPException(status_code=500, detail=f"数据库更新失败: {e}")
            finally:
                conn.execute("PRAGMA foreign_keys = ON")
        else:
            conn.execute(
                "UPDATE tiffs SET file_name=COALESCE(?, file_name), path_versions=?, "
                "tiff_type=COALESCE(?, tiff_type), updated_at=datetime('now') "
                "WHERE phase_id=? AND tiff_id=?",
                (image_name, path_versions, tiff_type, phase_id, tiff_id),
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
            raise HTTPException(status_code=409, detail=f"将移除 {count} 株推理结果、观测和相关运行记录，再次确认")
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
            else:
                from ...db.writer import update_tract_geom_from_tiffs
                update_tract_geom_from_tiffs(conn, tract_pk)
        conn.commit()
    finally:
        conn.close()
    return list_assets(db_url)


@router.get(
    "/tiffs/{phase_id}/{tiff_id}/delete-preview",
    response_model=AssetDeletePreview,
    summary="预览删除 TIFF 的影响范围",
)
def preview_delete_tiff(
    phase_id: str,
    tiff_id: str,
    db_url: str | None = Depends(get_db_url),
) -> AssetDeletePreview:
    conn = _connect(db_url)
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM tiffs WHERE phase_id=? AND tiff_id=?",
            (phase_id, tiff_id),
        ).fetchone()
        if not row or int(row["c"] or 0) == 0:
            raise HTTPException(status_code=404, detail="TIFF 不存在")
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM tree_observations WHERE phase_id=? AND tiff_id=?",
            (phase_id, tiff_id),
        ).fetchone()["c"]
    finally:
        conn.close()
    return AssetDeletePreview(
        phase_id=phase_id,
        tiff_id=tiff_id,
        observation_count=int(count or 0),
        requires_confirmation=bool(count),
    )
