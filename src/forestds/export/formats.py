"""林木定位与属性空间图层导出系统（阶段六补全）。

提供端到端将 SQLite 数据库中的单木观测数据导出为标准 GIS 图层文件的功能。
格式支持：CSV、GeoJSON、Shapefile (shp)、GeoPackage (gpkg)。
库依赖兼容：CSV/GeoJSON 采用 Python 原生模块实现（免安装依赖）；
Shapefile/GeoPackage 动态检测 geopandas 库，缺失时优雅自动降级为 GeoJSON 格式并提供明确的安装警报。
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from loguru import logger as log
from ..db import reader
from .. import paths


def parse_wkt_polygon(wkt: str | None) -> dict | None:
    """简单解析 WKT POLYGON((x1 y1, x2 y2, ...)) 为 GeoJSON Geometry dict"""
    if not wkt or not isinstance(wkt, str) or "POLYGON" not in wkt:
        return None
    try:
        s = wkt[wkt.index("((") + 2 : wkt.rindex("))")]
        rings = s.split("), (")
        coordinates = []
        for r in rings:
            ring_coords = []
            for pt_str in r.split(","):
                parts = pt_str.strip().split()
                if len(parts) >= 2:
                    ring_coords.append([float(parts[0]), float(parts[1])])
            coordinates.append(ring_coords)
        return {"type": "Polygon", "coordinates": coordinates}
    except Exception:
        return None


def parse_wkt_point(wkt: str | None) -> dict | None:
    """简单解析 WKT POINT(x y) 为 GeoJSON Geometry dict"""
    if not wkt or not isinstance(wkt, str) or "POINT" not in wkt:
        return None
    try:
        s = wkt[wkt.index("(") + 1 : wkt.rindex(")")]
        parts = s.strip().split()
        if len(parts) >= 2:
            return {"type": "Point", "coordinates": [float(parts[0]), float(parts[1])]}
    except Exception:
        return None


def export_tract_to_file(
    *,
    tract_id: str | None = None,
    run_id: str | None = None,
    fmt: str = "geojson",
    out_path: str | Path | None = None,
    db_url: str | None = None,
    crs_epsg: int | None = None,
    crs_wkt: str | None = None,
) -> dict:
    """从数据库读取并导出单木空间观测记录。

    参数：
      tract_id: 地块 ID（默认拉取最新地块）
      run_id: 限定某次推理运行的 run_id（可选）
      fmt: 导出格式，支持 'csv' / 'geojson' / 'shp' / 'gpkg'
      out_path: 输出文件路径（如果指定为目录，则自动在该目录下生成默认文件名）
      db_url: 自定义数据库连接

    返回结果字典：{'format': str, 'out_path': str, 'count': int, 'fallback': str | None}
    """
    fmt = fmt.lower().strip()
    if fmt not in ("csv", "geojson", "shp", "gpkg"):
        raise ValueError(f"不支持的导出格式: {fmt}。可选: csv, geojson, shp, gpkg")

    # 1. 确定地块 ID
    target_tract_id = tract_id
    if not target_tract_id:
        tracts = reader.list_tracts(url=db_url)
        if not tracts:
            raise ValueError("数据库中没有登记任何地块数据，无法导出")
        target_tract_id = tracts[0]["tract_id"]

    target_run_id = run_id
    if not target_run_id:
        target_run_id = reader.active_run_for_tract(target_tract_id, url=db_url)
        if not target_run_id:
            target_run_id = reader.latest_run_for_tract(target_tract_id, url=db_url)

    # 3. 确定空间参考 EPSG/WKT
    resolved_crs_epsg = crs_epsg
    resolved_crs_wkt = crs_wkt
    if not resolved_crs_epsg or not resolved_crs_wkt:
        try:
            tract_info = reader.get_tract(target_tract_id, url=db_url)
            if tract_info:
                if not resolved_crs_epsg:
                    resolved_crs_epsg = tract_info.get("crs_epsg")
                if not resolved_crs_wkt:
                    resolved_crs_wkt = tract_info.get("crs_wkt")
        except Exception as e:
            log.warning(f"获取地块空间参考失败: {e}")

    # 3.1 终极防御：若数据库中依然缺失空间参考，尝试从关联的 runs.input_path 影像文件中直接读取投影
    if not resolved_crs_epsg and not resolved_crs_wkt:
        try:
            if target_run_id:
                import sqlite3
                from ..db.schema import resolve_db_path
                conn = sqlite3.connect(resolve_db_path(db_url))
                try:
                    row = conn.execute(
                        "SELECT input_path FROM runs WHERE run_id=?", (target_run_id,)
                    ).fetchone()
                    if row and row[0]:
                        img_path = Path(row[0])
                        if img_path.exists():
                            import rasterio
                            with rasterio.open(img_path) as src:
                                if src.crs:
                                    if hasattr(src.crs, "to_wkt"):
                                        resolved_crs_wkt = src.crs.to_wkt()
                                    if hasattr(src.crs, "to_epsg"):
                                        resolved_crs_epsg = src.crs.to_epsg()
                                    log.info(f"从输入影像 {img_path} 成功回溯还原空间参考")
                finally:
                    conn.close()
        except Exception as autodetect_err:
            log.warning(f"自动回溯获取空间参考失败: {autodetect_err}")

    # 4. 拉取观测记录，强制转为 list 防止 generator 被多次消费
    observations: list[dict] = list(reader.fetch_observations(
        tract_id=target_tract_id, run_id=target_run_id, url=db_url
    ))
    if not observations:
        log.warning(f"地块 {target_tract_id} (run_id={target_run_id}) 暂无观测树木记录。将导出空数据集。")

    # 4. 确定最终输出文件的具体物理路径
    out_dir = Path(out_path) if out_path else paths.outputs_postprocess_dir()
    if out_dir.is_dir() or not out_dir.suffix:
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = f"export_{target_tract_id}"
        if target_run_id:
            stem += f"_{target_run_id}"
        ext = f".{fmt}" if fmt != "geojson" else ".geojson"
        final_path = out_dir / (stem + ext)
    else:
        final_path = out_dir
        final_path.parent.mkdir(parents=True, exist_ok=True)

    result_info = {
        "format": fmt,
        "out_path": str(final_path),
        "count": len(observations),
        "fallback": None,
    }

    # 5. 执行具体格式的序列化工作
    if fmt == "csv":
        with open(final_path, "w", newline="", encoding="utf-8") as csvfile:
            writer_csv = csv.writer(csvfile)
            writer_csv.writerow([
                "observation_id", "species", "confidence",
                "crown_width_geo", "crown_height_geo",
                "crown_area_px",
                "crown_area_geo_est", "crown_area_geo_real",
                "crown_volume_geo_est", "crown_volume_geo_real",
                "height", "height_source", "geom_crown", "geom_point",
                "box_px_sub", "source_subimage_path", "run_id"
            ])
            for obs in observations:
                writer_csv.writerow([
                    obs.get("observation_id"),
                    obs.get("species"),
                    obs.get("confidence"),
                    obs.get("crown_width_geo"),
                    obs.get("crown_height_geo"),
                    obs.get("crown_area_px"),
                    obs.get("crown_area_geo_est"),
                    obs.get("crown_area_geo_real"),
                    obs.get("crown_volume_geo_est"),
                    obs.get("crown_volume_geo_real"),
                    obs.get("height"),
                    obs.get("height_source"),
                    obs.get("geom_crown"),
                    obs.get("geom_point"),
                    obs.get("box_px_sub"),
                    obs.get("source_subimage_path"),
                    obs.get("run_id"),
                ])
                
    elif fmt == "geojson":
        features = []
        for obs in observations:
            geom = None
            if obs.get("geom_crown"):
                geom = parse_wkt_polygon(obs["geom_crown"])
            if geom is None and obs.get("geom_point"):
                geom = parse_wkt_point(obs["geom_point"])
                
            properties = {
                "observation_id": obs.get("observation_id"),
                "species": obs.get("species"),
                "confidence": obs.get("confidence"),
                "crown_width_geo": obs.get("crown_width_geo"),
                "crown_height_geo": obs.get("crown_height_geo"),
                "crown_area_px": obs.get("crown_area_px"),
                "crown_area_geo_est": obs.get("crown_area_geo_est"),
                "crown_area_geo_real": obs.get("crown_area_geo_real"),
                "crown_volume_geo_est": obs.get("crown_volume_geo_est"),
                "crown_volume_geo_real": obs.get("crown_volume_geo_real"),
                "height": obs.get("height"),
                "height_source": obs.get("height_source"),
                "run_id": obs.get("run_id"),
                "tract_id": obs.get("tract_id"),
            }
            features.append({
                "type": "Feature",
                "geometry": geom,
                "properties": properties
            })
        geojson_data = {
            "type": "FeatureCollection",
            "features": features
        }
        with open(final_path, "w", encoding="utf-8") as f_json:
            json.dump(geojson_data, f_json, ensure_ascii=False, indent=2)
            
    else:  # shp 或者 gpkg
        # 动态检查环境中的依赖
        gpd = None
        shapely_wkt = None
        try:
            import geopandas as gpd
            from shapely.wkt import loads as shapely_wkt
        except ImportError:
            pass

        if gpd is None or shapely_wkt is None:
            # 优雅自动降级到 geojson 格式
            fallback_path = final_path.with_suffix(".geojson")
            log.warning(
                f"环境缺少 geopandas 或 shapely 空间处理库，[{fmt}] 格式导出失败。"
                f"系统已自动降级为输出零依赖的 GeoJSON 格式文件 -> {fallback_path}。"
                f"如需完整导出 Shapefile/GeoPackage 格式，请在终端执行 'uv add geopandas shapely' 安装包。"
            )
            result_info["fallback"] = f"{fmt} -> geojson (geopandas 库缺失)"
            result_info["format"] = "geojson"
            result_info["out_path"] = str(fallback_path)
            
            # 递归调用以生成 geojson
            return export_tract_to_file(
                tract_id=target_tract_id,
                run_id=target_run_id,
                fmt="geojson",
                out_path=fallback_path,
                db_url=db_url,
                crs_epsg=resolved_crs_epsg,
                crs_wkt=resolved_crs_wkt,
            )
            
        # 使用 geopandas 导出
        data_list = []
        for obs in observations:
            geom = None
            if obs.get("geom_crown"):
                try:
                    geom = shapely_wkt(obs["geom_crown"])
                except Exception:
                    pass
            if geom is None and obs.get("geom_point"):
                try:
                    geom = shapely_wkt(obs["geom_point"])
                except Exception:
                    pass
                    
            data_list.append({
                "geometry": geom,
                "observation_id": obs.get("observation_id"),
                "species": obs.get("species"),
                "confidence": obs.get("confidence"),
                "crown_width_geo": obs.get("crown_width_geo"),
                "crown_height_geo": obs.get("crown_height_geo"),
                "area_px": obs.get("crown_area_px"),
                "area_geo_est": obs.get("crown_area_geo_est"),
                "area_geo_real": obs.get("crown_area_geo_real"),
                "volume_est": obs.get("crown_volume_geo_est"),
                "volume_real": obs.get("crown_volume_geo_real"),
                "height": obs.get("height"),
                "height_src": obs.get("height_source"),
                "run_id": obs.get("run_id"),
                "tract_id": obs.get("tract_id"),
            })
            
        # 若列表为空，为了防止 pandas 报错，需要提供结构化模板
        if not data_list:
            data_list = [{
                "geometry": None, "observation_id": None, "species": None, "confidence": None,
                "crown_width_geo": None, "crown_height_geo": None,
                "area_px": None,
                "area_geo_est": None, "area_geo_real": None,
                "volume_est": None, "volume_real": None,
                "height": None, "height_src": None, "run_id": None, "tract_id": None
            }]
            
        gdf = gpd.GeoDataFrame(data_list)
        if resolved_crs_wkt:
            gdf.crs = resolved_crs_wkt
        elif resolved_crs_epsg:
            gdf.crs = f"EPSG:{resolved_crs_epsg}"
        driver = "ESRI Shapefile" if fmt == "shp" else "GPKG"
        gdf.to_file(final_path, driver=driver)

    log.info(f"空间图层成功导出[{result_info['format']}]，检测数={result_info['count']} -> {result_info['out_path']}")
    return result_info
