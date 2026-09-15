"""单木物理指标原地重算与回填工具。

职责：
  - 从数据库读取已有的单木检测框 (BBox)；
  - 基于最新的高程基底校准 (宏观泥面分位数滤波)、垂直断层截断与欠采样孔洞弥合算法；
  - 重新采样并计算树高、真实冠幅面积、真实体积与几何估计体积；
  - 原地事务性 UPDATE 回填 tree_observations 数据库表，无需重跑深度学习检测。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from loguru import logger as log

from ..db.schema import get_db_connection
from ..detect.base import Detection
from ..fusion.chm import CHMSampler, chm_from_las, chm_from_dsm_dem, load_single_band
from ..geo import resolve_geo


def recalculate_run_metrics(
    run_id: str,
    db_url: str | Path | None = None,
    dry_run: bool = False,
    macro_ground_filter: bool = True,
    filter_vertical_gap: bool = True,
    impute_canopy_holes: bool = True,
) -> dict:
    """针对指定的 run_id 原地重算单木高程、真实面积和体积指标并回填数据库。"""
    conn = get_db_connection(db_url)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT run_id, phase_id, tiff_id, task_type, input_path, params_json FROM runs WHERE run_id = ?",
        (run_id,),
    )
    row = cursor.fetchone()
    if not row:
        raise ValueError(f"未找到 run_id={run_id} 的运行记录")

    _, phase_id, tiff_id, task_type, input_path, params_json_raw = row
    params = json.loads(params_json_raw) if params_json_raw else {}

    las_path = params.get("las")
    chm_path = params.get("chm")
    dsm_path = params.get("dsm")
    dem_path = params.get("dem")
    image_path = params.get("image_path") or input_path

    if not las_path and not chm_path and not dsm_path:
        log.warning("Run {} 未配置任何多源点云或高程数据 (las/chm/dsm 均为空)，无需重算", run_id)
        return {"run_id": run_id, "updated": 0, "status": "skipped_no_elevation"}

    log.info("【指标重算】开始处理 run_id={} (时相={}, 影像={})", run_id, phase_id, image_path)

    # 1. 加载正射影像地理信息
    rgb_geo = None
    if image_path and Path(image_path).exists():
        try:
            import rasterio
            with rasterio.open(image_path) as ds:
                rgb_geo = resolve_geo(image_path, transform=ds.transform, crs=ds.crs)
            log.info("成功载入正射影像 GeoInfo: 尺寸={}x{}, CRS={}", ds.width, ds.height, ds.crs)
        except Exception as e:
            log.warning("读取正射影像地理信息失败: {}", e)

    # 2. 构建 CHMSampler
    las_grid_size = params.get("las_grid_size") or 0.05
    sampler: Optional[CHMSampler] = None

    if las_path and Path(las_path).exists():
        log.info("使用点云构建高精度 CHM: {} (网格大小={:.3f}m, 基底滤波={})", las_path, las_grid_size, macro_ground_filter)
        t0 = time.time()
        chm, chm_geo, raw_pts = chm_from_las(
            las_path,
            grid_size=las_grid_size,
            rgb_geo=rgb_geo,
            macro_ground_filter=macro_ground_filter,
        )
        log.info("点云解析与滤波完成，耗时={:.2f}s, CHM 尺寸={}", time.time() - t0, chm.shape)

        sampler = CHMSampler(
            chm=chm,
            chm_transform=chm_geo.transform if chm_geo else None,
            rgb_transform=rgb_geo.transform if rgb_geo else None,
            chm_geo=chm_geo,
            rgb_geo=rgb_geo,
            stat="max",
            volume_method="cbh",
            cbh_factor=0.3,
            find_real_canopy=True,
            filter_vertical_gap=filter_vertical_gap,
            impute_canopy_holes=impute_canopy_holes,
            raw_points=raw_pts,
        )
    elif chm_path and Path(chm_path).exists():
        chm, chm_geo = load_single_band(chm_path)
        sampler = CHMSampler(
            chm=chm,
            chm_transform=chm_geo.transform if chm_geo else None,
            rgb_transform=rgb_geo.transform if rgb_geo else None,
            chm_geo=chm_geo,
            rgb_geo=rgb_geo,
            find_real_canopy=True,
            filter_vertical_gap=filter_vertical_gap,
            impute_canopy_holes=impute_canopy_holes,
        )
    elif dsm_path and dem_path and Path(dsm_path).exists() and Path(dem_path).exists():
        dsm_arr, dsm_geo = load_single_band(dsm_path)
        dem_arr, dem_geo = load_single_band(dem_path)
        chm = chm_from_dsm_dem(dsm_arr, dem_arr)
        sampler = CHMSampler(
            chm=chm,
            chm_transform=dsm_geo.transform if dsm_geo else None,
            rgb_transform=rgb_geo.transform if rgb_geo else None,
            chm_geo=dsm_geo,
            rgb_geo=rgb_geo,
            dsm=dsm_arr,
            dem=dem_arr,
            dem_geo=dem_geo,
            source_name="dsm_dem",
            find_real_canopy=True,
            filter_vertical_gap=filter_vertical_gap,
            impute_canopy_holes=impute_canopy_holes,
        )
    else:
        raise FileNotFoundError(f"未找到有效的高程源文件: las={las_path}, chm={chm_path}, dsm={dsm_path}")

    # 3. 查询单木记录并重算
    cursor.execute(
        "SELECT observation_id, box_px, height, crown_area_geo_real, crown_volume_geo_real, crown_volume_geo_est "
        "FROM tree_observations WHERE run_id = ?",
        (run_id,),
    )
    obs_rows = cursor.fetchall()
    total_trees = len(obs_rows)
    log.info("查出属于 run_id={} 的单木观测记录 {} 棵，开始批量重算...", run_id, total_trees)

    update_payloads = []
    old_heights = []
    new_heights = []
    old_areas = []
    new_areas = []
    old_vols = []
    new_vols = []

    t0 = time.time()
    for row in obs_rows:
        obs_id = row["observation_id"]
        box_px_raw = row["box_px"]
        old_h = row["height"]
        old_area = row["crown_area_geo_real"]
        old_vol = row["crown_volume_geo_real"]

        if old_h is not None:
            old_heights.append(old_h)
        if old_area is not None:
            old_areas.append(old_area)
        if old_vol is not None:
            old_vols.append(old_vol)

        box_px = json.loads(box_px_raw) if box_px_raw else None
        if not box_px or len(box_px) < 4:
            continue

        det = Detection(x1=float(box_px[0]), y1=float(box_px[1]), x2=float(box_px[2]), y2=float(box_px[3]), score=1.0)
        res = sampler.metrics_for_detection(det)

        if "error" in res:
            new_h = None
            new_area = None
            new_vol_real = None
            new_vol_est = None
        else:
            new_h = res.get("height")
            new_area = res.get("crown_area_geo_real")
            new_vol_real = res.get("volume_real")
            new_vol_est = res.get("volume_est")

            if new_h is not None:
                new_heights.append(new_h)
            if new_area is not None:
                new_areas.append(new_area)
            if new_vol_real is not None:
                new_vols.append(new_vol_real)

        update_payloads.append((new_h, new_area, new_vol_real, new_vol_est, obs_id))

    calc_duration = time.time() - t0
    log.info("单木指标重算完成: 处理 {} 棵树，耗时={:.2f}s ({:.1f} 棵/秒)", len(update_payloads), calc_duration, len(update_payloads) / max(calc_duration, 1e-4))

    # 4. 批量回填更新数据库
    if not dry_run and update_payloads:
        t_up = time.time()
        cursor.executemany(
            "UPDATE tree_observations SET "
            "  height = ?, "
            "  crown_area_geo_real = ?, "
            "  crown_volume_geo_real = ?, "
            "  crown_volume_geo_est = ? "
            "WHERE observation_id = ?",
            update_payloads,
        )
        conn.commit()
        log.info("数据库事务提交完成，成功更新 {} 条记录，耗时={:.2f}s", len(update_payloads), time.time() - t_up)
    elif dry_run:
        log.info("【Dry Run 模式】未实际写入数据库")

    conn.close()

    summary = {
        "run_id": run_id,
        "total_trees": total_trees,
        "updated_trees": len(update_payloads),
        "dry_run": dry_run,
        "old_stats": {
            "mean_height": float(sum(old_heights) / len(old_heights)) if old_heights else None,
            "max_height": float(max(old_heights)) if old_heights else None,
            "mean_real_area": float(sum(old_areas) / len(old_areas)) if old_areas else None,
            "total_real_volume": float(sum(old_vols)) if old_vols else None,
        },
        "new_stats": {
            "mean_height": float(sum(new_heights) / len(new_heights)) if new_heights else None,
            "max_height": float(max(new_heights)) if new_heights else None,
            "mean_real_area": float(sum(new_areas) / len(new_areas)) if new_areas else None,
            "total_real_volume": float(sum(new_vols)) if new_vols else None,
        },
    }
    return summary


def recalculate_all_runs(db_url: str | Path | None = None, dry_run: bool = False) -> list[dict]:
    """遍历所有包含多源高程配置的 run 并执行指标重算。"""
    conn = get_db_connection(db_url)
    cursor = conn.cursor()
    cursor.execute("SELECT run_id, params_json FROM runs")
    runs_to_process = []
    for r_id, p_raw in cursor.fetchall():
        if not p_raw:
            continue
        try:
            p = json.loads(p_raw)
            if p.get("las") or p.get("chm") or p.get("dsm"):
                # 确认该 run 确实有 tree_observations
                c = conn.execute("SELECT count(*) FROM tree_observations WHERE run_id = ?", (r_id,)).fetchone()[0]
                if c > 0:
                    runs_to_process.append(r_id)
        except Exception:
            pass
    conn.close()

    log.info("共发现 {} 个包含高程点云的运行任务待重算: {}", len(runs_to_process), runs_to_process)
    results = []
    for r_id in runs_to_process:
        res = recalculate_run_metrics(r_id, db_url=db_url, dry_run=dry_run)
        results.append(res)
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="4estDS 单木物理指标原地重算与回填工具")
    parser.add_argument("--run-id", "-r", help="指定要重算的 run_id，不指定则自动处理所有含点云的 run")
    parser.add_argument("--dry-run", action="store_true", help="只演练计算指标，不实际写入数据库")
    args = parser.parse_args()

    if args.run_id:
        recalculate_run_metrics(args.run_id, dry_run=args.dry_run)
    else:
        recalculate_all_runs(dry_run=args.dry_run)
