"""影像资产台账端点。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from loguru import logger as log

from fastapi import APIRouter, Depends, HTTPException, Query

from ...db import writer
from ...db.schema import init_db, resolve_db_path
from ...geo.admin import UNKNOWN_COUNTY, UNKNOWN_TOWN, inspect_image_center, region_id as make_region_id, split_region_id
from ...utils.input_inspect import inspect_input_path
from ...utils.input_inspect import normalize_user_path
from ..deps import get_db_url
from .geo import AmapConfigError, AmapServiceError, reverse_admin
from ..schemas import (
    AssetCogCancelOut,
    AssetCogCancelRequest,
    AssetCogConvertOut,
    AssetCogConvertRequest,
    AssetCogStatusOut,
    AssetDeletePreview,
    AssetInspectOut,
    AssetInspectRequest,
    AssetPatch,
    AssetRow,
    AssetTiffCreate,
    ServerFileItem,
    ServerFileBrowseOut,
)

router = APIRouter(prefix="/assets", tags=["assets"])


def _connect(url: str | None) -> sqlite3.Connection:
    init_db(url)
    from ...db.schema import get_db_connection
    return get_db_connection(url)


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

        tiff_type = row.get("tiff_type")
        estimated_cog_seconds = None
        if tiff_type and tiff_type != "COG" and tiff_type != "invalid":
            from ...preprocess.cog import estimate_cog_seconds
            estimated_cog_seconds = estimate_cog_seconds(
                row.get("pixel_width"), row.get("pixel_height")
            )

        file_size_gb: float | None = None
        file_exists: bool = False
        source_path = row.get("source_path")
        if source_path:
            try:
                norm_p = normalize_user_path(source_path)
                p = Path(norm_p)
                if p.is_file():
                    file_exists = True
                    try:
                        file_size_gb = round(p.stat().st_size / (1024 ** 3), 2)
                    except OSError:
                        file_size_gb = None
            except Exception:
                file_exists = False

        if file_size_gb is None and row.get("pixel_width") and row.get("pixel_height"):
            # 如果源文件不在本地，从分辨率粗略估算解压 Raw Byte 大小 (3 通道 uint8)
            raw_bytes = int(row["pixel_width"]) * int(row["pixel_height"]) * int(row.get("band_count") or 3)
            file_size_gb = round(raw_bytes / (1024 ** 3), 2)

        is_converting = False
        if source_path:
            try:
                from ...preprocess.cog import get_cog_task_status
                norm_p = str(Path(normalize_user_path(source_path)).expanduser().resolve())
                task_st = get_cog_task_status(norm_p)
                if task_st.get("is_converting") or norm_p in _active_cog_locks or source_path in _active_cog_locks:
                    is_converting = True
            except Exception:
                pass

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
                tiff_type=tiff_type,
                active_run_id=row.get("active_run_id"),
                run_id=row.get("run_id"),
                run_count=int(row.get("run_count") or 0),
                run_status_counts=row.get("run_status_counts") or {},
                active_run_status=row.get("active_run_status"),
                status=row.get("status") or "未检测",
                footprint_area_hm2=row.get("footprint_area_hm2"),
                area_hm2=(row.get("area_hm2") if (row.get("area_hm2") is not None and row.get("area_hm2") > 0) else (row.get("footprint_area_hm2") or row.get("tiff_effective_area_hm2"))),
                geo_area=(row.get("area_hm2") if (row.get("area_hm2") is not None and row.get("area_hm2") > 0) else (row.get("footprint_area_hm2") or row.get("tiff_effective_area_hm2"))),
                observation_count=int(row.get("observation_count") or 0),
                detected_at=row.get("detected_at"),
                pixel_width=row.get("pixel_width"),
                pixel_height=row.get("pixel_height"),
                estimated_cog_seconds=estimated_cog_seconds,
                file_size_gb=file_size_gb,
                is_converting=is_converting,
                file_exists=file_exists,
                effective_area_hm2=row.get("tiff_effective_area_hm2") if row.get("tiff_effective_area_hm2") is not None else row.get("area_hm2"),
                tract_area_hm2=row.get("effective_area_hm2"),
                tract_phase_area_hm2=row.get("tract_phase_area_hm2"),
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

    estimated_cog_seconds = None
    if image and tiff_type and tiff_type != "COG" and tiff_type != "invalid":
        from ...preprocess.cog import estimate_cog_seconds
        estimated_cog_seconds = estimate_cog_seconds(image.width, image.height)

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
        estimated_cog_seconds=estimated_cog_seconds,
    )


@router.get("/cog-status", response_model=AssetCogStatusOut, summary="获取指定 TIFF 的物理真实转码进度与 ETA")
def get_asset_cog_status(path: str = Query(..., description="TIFF 源文件路径")) -> AssetCogStatusOut:
    from ...preprocess.cog import get_cog_task_status
    normalized = normalize_user_path(path)
    res = get_cog_task_status(normalized)
    return AssetCogStatusOut(**res)


_active_cog_locks: set[str] = set()


@router.post("/convert-cog", response_model=AssetCogConvertOut, summary="将单个 TIFF 转为严格 COG")
def convert_asset_cog(body: AssetCogConvertRequest, db_url: str | None = Depends(get_db_url)) -> AssetCogConvertOut:
    from ...preprocess.cog import (
        TIFF_COG,
        TIFF_FORMAT_LABELS,
        inspect_tiff_format,
        prepared_cog_path,
        calculate_exact_effective_ratio,
    )
    from ...db.writer import _compute_tiff_metadata

    normalized = normalize_user_path(body.input_path)
    path = Path(normalized).expanduser().resolve()
    lock_key = str(path)

    if lock_key in _active_cog_locks:
        raise HTTPException(status_code=409, detail="该文件正在转码中，请勿重复操作")

    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"TIFF 不存在: {path}")
    if path.suffix.lower() not in {".tif", ".tiff"}:
        raise HTTPException(status_code=415, detail="只支持 tif/tiff 单文件转换")

    _active_cog_locks.add(lock_key)
    try:
        source_type = inspect_tiff_format(path)
        cog_path, prepared_type = prepared_cog_path(path, force=True)
        if prepared_type != TIFF_COG:
            raise HTTPException(status_code=500, detail=f"COG 转换失败: {prepared_type}")
    finally:
        _active_cog_locks.discard(lock_key)

    # 【方案B】：转码成功后，100% 精准更新数据库里的物理数据与有效面积
    if prepared_type == TIFF_COG:
        try:
            exact_ratio = calculate_exact_effective_ratio(cog_path)
            tiff_meta = _compute_tiff_metadata(
                cog_path,
                phase_id="00000000",
                tract_phase_pk="dummy",
            )
            if tiff_meta:
                exact_effective_area = None
                if tiff_meta.get("footprint_area_hm2") is not None:
                    exact_effective_area = round(tiff_meta["footprint_area_hm2"] * exact_ratio, 4)

                conn = _connect(db_url)
                try:
                    # 匹配包含该 TIFF 文件路径的行
                    rows = conn.execute(
                        "SELECT tiff_id, phase_id, tract_phase_pk FROM tiffs "
                        "WHERE path_versions LIKE ? OR path_versions LIKE ?",
                        (f"%{str(path)}%", f"%{body.input_path}%")
                    ).fetchall()
                    for r in rows:
                        t_id = r["tiff_id"]
                        ph_id = r["phase_id"]
                        tp_pk = r["tract_phase_pk"]

                        tp_row = conn.execute(
                            "SELECT tract_pk FROM tract_phases WHERE tract_phase_pk=?",
                            (tp_pk,)
                        ).fetchone()

                        # 更新 tiffs 表数据属性与精确有效面积
                        conn.execute(
                            "UPDATE tiffs SET "
                            "path_versions=?, tiff_type=?, "
                            "pixel_width=?, pixel_height=?, footprint_area_hm2=?, "
                            "area_hm2=?, updated_at=datetime('now') "
                            "WHERE tiff_id=? AND phase_id=?",
                            (
                                json.dumps([str(x) for x in tiff_meta["path_versions"]]) if isinstance(tiff_meta["path_versions"], (list, tuple)) else str(tiff_meta["path_versions"]),
                                "COG",
                                tiff_meta["pixel_width"],
                                tiff_meta["pixel_height"],
                                tiff_meta.get("footprint_area_hm2"),
                                exact_effective_area,
                                t_id,
                                ph_id,
                            )
                        )
                    conn.commit()
                finally:
                    conn.close()
        except Exception as e:
            log.warning("转 COG 后更新数据库失败: {}", e)

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


@router.post("/cancel-cog", response_model=AssetCogCancelOut, summary="取消/终止指定 TIFF 的 COG 转码任务")
def cancel_asset_cog(body: AssetCogCancelRequest) -> AssetCogCancelOut:
    from ...preprocess.cog import cancel_cog_task

    normalized = normalize_user_path(body.input_path)
    path = Path(normalized).expanduser().resolve()
    lock_key = str(path)

    for k in (lock_key, body.input_path, str(path.resolve()), normalized):
        if k:
            _active_cog_locks.discard(k)
    cancelled = True

    task_cancelled = cancel_cog_task(path) or cancel_cog_task(body.input_path)
    cancelled = cancelled or task_cancelled

    msg = "已终止该 TIFF 的 COG 转码任务并释放锁" if cancelled else "该文件未在转码中"
    log.info("手动终止 COG 转码: path={} cancelled={}", body.input_path, cancelled)
    return AssetCogCancelOut(message=msg, cancelled=cancelled)


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


@router.get("/browse-files", response_model=ServerFileBrowseOut, summary="浏览服务器本地文件与目录")
def browse_files(path: str | None = Query(None)) -> ServerFileBrowseOut:
    import os
    if not path:
        target_path = Path("/").resolve()
    else:
        target_path = Path(path).resolve()

    if not target_path.exists():
        raise HTTPException(status_code=404, detail="路径不存在")
    if not target_path.is_dir():
        raise HTTPException(status_code=400, detail="指定路径不是一个有效的目录")

    items = []
    try:
        for entry in os.scandir(target_path):
            if entry.name.startswith("."):
                continue
            is_dir = entry.is_dir()
            
            if not is_dir:
                ext = Path(entry.name).suffix.lower()
                if ext not in {".tif", ".tiff", ".las", ".dem", ".dsm", ".shp", ".geojson", ".zip", ".json"}:
                    continue

            try:
                stat = entry.stat()
                size = stat.st_size
            except OSError:
                size = None

            items.append(
                ServerFileItem(
                    name=entry.name,
                    path=str(Path(entry.path).absolute()),
                    is_dir=is_dir,
                    size=size,
                )
            )
    except PermissionError:
        raise HTTPException(status_code=403, detail="没有权限访问该目录")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    items.sort(key=lambda x: (not x.is_dir, x.name.lower()))
    
    parent_path = str(target_path.parent) if target_path != target_path.parent else None

    return ServerFileBrowseOut(
        current_path=str(target_path),
        parent_path=parent_path,
        items=items,
    )
