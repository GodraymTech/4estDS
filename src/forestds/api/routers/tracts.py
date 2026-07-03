"""地块“一张图”与台账端点。

- GET /tracts                          地块台账列表
- GET /tracts/{id}                     单地块详情
- GET /tracts/{id}/observations        观测图层 GeoJSON(供 MapLibre)
- GET /tracts/{id}/report              在线报告(返回文件)
- GET /tracts/{id}/export              GIS 图层导出(返回文件)
- GET /tracts/{id}/changes             时序变化对比(两 run)

默认使用地块的 active_run(已发布版本)；可用 run_id 参数指定。均复用现有 reader/report/export。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from ..deps import get_db_url
from ..geojson import rows_to_featurecollection
from ..schemas import ChangeCompareOut, TractImageryOut, TractOut

router = APIRouter(prefix="/tracts", tags=["tracts"])


def _resolve_run(tract_id: str, run_id: str | None, db_url: str | None) -> str | None:
    """解析要展示的 run: 显式 run_id > active_run(已发布) > latest_run(成功)。"""
    from ...db import reader

    if run_id:
        return run_id
    return reader.active_run_for_tract(tract_id, url=db_url) or reader.latest_run_for_tract(
        tract_id, url=db_url
    )


@router.get("", response_model=list[TractOut], summary="地块台账列表")
def list_tracts(db_url: str | None = Depends(get_db_url)) -> list[TractOut]:
    from ...db import reader

    return [TractOut(**t) for t in reader.list_tracts(url=db_url)]


@router.get("/{tract_id}", response_model=TractOut, summary="地块详情")
def get_tract(tract_id: str, db_url: str | None = Depends(get_db_url)) -> TractOut:
    from ...db import reader

    tract = reader.get_tract(tract_id, url=db_url)
    if tract is None:
        raise HTTPException(status_code=404, detail=f"地块不存在: {tract_id}")
    return TractOut(**tract)


def _derive_imagery(tract: dict) -> dict:
    """从地块元数据派生多时相真影像瓦片配置。

    约定优先级: imagery_tiles(list) > imagery_tiles_url / tiles_url(单模板)。
    未配置则 tiles=None(available=False), 前端回退默认底图。
    """
    tiles: list[str] | None = None
    raw = tract.get("imagery_tiles")
    if isinstance(raw, list) and raw:
        tiles = [str(t) for t in raw]
    else:
        url = tract.get("imagery_tiles_url") or tract.get("tiles_url")
        if isinstance(url, str) and url:
            tiles = [url]
    return {
        "tiles": tiles,
        "tile_size": int(tract.get("imagery_tile_size") or 256),
        "attribution": tract.get("imagery_attribution"),
        "min_zoom": tract.get("imagery_min_zoom"),
        "max_zoom": tract.get("imagery_max_zoom"),
    }


@router.get("/{tract_id}/imagery", response_model=TractImageryOut, summary="多时相真影像瓦片")
def get_imagery(tract_id: str, db_url: str | None = Depends(get_db_url)) -> TractImageryOut:
    from ...db import reader

    tract = reader.get_tract(tract_id, url=db_url)
    if tract is None:
        raise HTTPException(status_code=404, detail=f"地块不存在: {tract_id}")
    d = _derive_imagery(tract)
    return TractImageryOut(
        tract_id=tract_id,
        acquisition_time=tract.get("acquisition_time"),
        tiles=d["tiles"],
        tile_size=d["tile_size"],
        attribution=d["attribution"],
        min_zoom=d["min_zoom"],
        max_zoom=d["max_zoom"],
        available=bool(d["tiles"]),
    )


@router.get("/{tract_id}/observations", summary="观测图层 GeoJSON")
def get_observations(
    tract_id: str,
    run_id: str | None = Query(None, description="指定 run，缺省用已发布/最新成功 run"),
    geometry: str = Query("point", pattern="^(point|crown)$", description="point 或 crown"),
    db_url: str | None = Depends(get_db_url),
) -> JSONResponse:
    from ...db import reader

    rid = _resolve_run(tract_id, run_id, db_url)
    if rid is None:
        return JSONResponse({"type": "FeatureCollection", "features": []})
    rows = reader.fetch_observations(run_id=rid, tract_id=tract_id, url=db_url)
    return JSONResponse(rows_to_featurecollection(rows, geometry=geometry))


@router.get("/{tract_id}/report", summary="在线报告")
def get_report(
    tract_id: str,
    run_id: str | None = Query(None),
    fmt: str = Query("pdf", pattern="^(pdf|md|csv)$"),
    db_url: str | None = Depends(get_db_url),
):
    from ... import paths
    from ...report import generate_report

    rid = _resolve_run(tract_id, run_id, db_url)
    if rid is None:
        raise HTTPException(status_code=404, detail="该地块尚无可用运行，无法生成报告")
    out_dir = paths.home_dir() / "outputs" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = generate_report(
            tract_id, rid, fmt=fmt, out_dir=str(out_dir), db_url=db_url, with_charts=True
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"报告生成失败: {exc}")
    out_path = result.get("out_path") if isinstance(result, dict) else None
    if not out_path or not Path(out_path).exists():
        raise HTTPException(status_code=500, detail="报告生成失败: 未产出文件")
    return FileResponse(out_path, filename=Path(out_path).name)


@router.get("/{tract_id}/export", summary="GIS 图层导出")
def export_tract(
    tract_id: str,
    fmt: str = Query("geojson", pattern="^(geojson|shp|gpkg|csv)$"),
    run_id: str | None = Query(None),
    db_url: str | None = Depends(get_db_url),
):
    from ... import paths
    from ...db import reader
    from ...export.formats import export_tract_to_file

    rid = _resolve_run(tract_id, run_id, db_url)
    if rid is None:
        raise HTTPException(status_code=404, detail="该地块尚无可用运行，无法导出")
    tract = reader.get_tract(tract_id, url=db_url) or {}
    out_dir = paths.home_dir() / "outputs" / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{tract_id}_{rid}.{fmt if fmt != 'shp' else 'zip'}"
    try:
        result = export_tract_to_file(
            tract_id=tract_id, run_id=rid, fmt=fmt, out_path=str(out_path),
            db_url=db_url, crs_epsg=tract.get("crs_epsg"), crs_wkt=tract.get("crs_wkt"),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"导出失败: {exc}")
    final = result.get("out_path", str(out_path)) if isinstance(result, dict) else str(out_path)
    if not Path(final).exists():
        raise HTTPException(status_code=500, detail="导出失败: 未产出文件")
    return FileResponse(final, filename=Path(final).name)


def _sum_crown_area(rows: list[dict]) -> float | None:
    vals = [r.get("crown_area_geo_real") or r.get("crown_area_geo_est") for r in rows]
    vals = [v for v in vals if isinstance(v, (int, float))]
    return round(sum(vals), 4) if vals else None


@router.get("/{tract_id}/changes", response_model=ChangeCompareOut, summary="时序变化对比")
def compare_changes(
    tract_id: str,
    base: str = Query(..., description="基准 run_id"),
    target: str = Query(..., description="对比 run_id"),
    db_url: str | None = Depends(get_db_url),
) -> ChangeCompareOut:
    from ...db import reader

    base_rows = reader.fetch_observations(run_id=base, tract_id=tract_id, url=db_url)
    target_rows = reader.fetch_observations(run_id=target, tract_id=tract_id, url=db_url)
    base_area = _sum_crown_area(base_rows)
    target_area = _sum_crown_area(target_rows)
    delta_area = (
        round(target_area - base_area, 4)
        if base_area is not None and target_area is not None
        else None
    )
    return ChangeCompareOut(
        tract_id=tract_id,
        base_run_id=base,
        target_run_id=target,
        base_count=len(base_rows),
        target_count=len(target_rows),
        delta_count=len(target_rows) - len(base_rows),
        base_crown_area=base_area,
        target_crown_area=target_area,
        delta_crown_area=delta_area,
    )
