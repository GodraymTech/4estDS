"""多源高程渠道（DSM、DSM+DEM、点云）及树高/体积提取测试。"""
import os
import sys
from pathlib import Path

# 添加 src 到 Python 搜索路径
src_path = str(Path(__file__).parent.parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

import numpy as np
from loguru import logger

from forestds.geo import resolve_geo
from forestds.fusion.chm import build_chm_sampler
from forestds.detect.base import Detection
from forestds.db import schema, writer, reader

# 测试数据路径定义
IMAGE_PATH = "data/xuwen_big.tif"
DSM_PATH = "data/xuwen_multisource/DSM/dsm.tif"
DEM_PATH = "data/xuwen_multisource/DEM/dem.tif"
LAS_PATH = "data/xuwen_multisource/激光点云/cloud0.las"
TEST_DB_URL = "sqlite:///data/test_db.sqlite"  # 使用本地临时测试库


def get_valid_test_det(rgb_geo) -> Detection:
    """读取点云地理范围中心，反算其在 RGB 中的像素坐标以生成必定有高程数据的测试框。"""
    import laspy
    with laspy.open(LAS_PATH) as fh:
        las = fh.read()
    center_x = float(np.mean(las.x))
    center_y = float(np.mean(las.y))
    
    # 转换回 RGB 的像素坐标
    cx_px, cy_px = rgb_geo.transform.world_to_pixel(center_x, center_y)
    
    # 构建 3m * 3m 的检测框
    dx_px = 3.0 / rgb_geo.transform.pixel_size_x()
    dy_px = 3.0 / abs(rgb_geo.transform.pixel_size_y())
    
    return Detection(
        x1=cx_px - dx_px/2, y1=cy_px - dy_px/2,
        x2=cx_px + dx_px/2, y2=cy_px + dy_px/2,
        score=0.95, label="tree"
    )


def test_dsm_only_mode():
    logger.info("============== 1. 测试单独 DSM 模式 ==============")
    rgb_geo = resolve_geo(IMAGE_PATH)
    assert rgb_geo is not None, "RGB 影像应包含地理参考"
    
    # 仅指定 DSM, DEM 默认常量 0.0m
    sampler = build_chm_sampler(
        dsm_path=DSM_PATH,
        dem_default_value=0.0,
        rgb_geo=rgb_geo,
        stat="max",
    )
    assert sampler is not None, "单独 DSM 模式下构建 Sampler 失败"
    
    # 模拟一个正好落在覆盖区的检测框
    det = get_valid_test_det(rgb_geo)
    h, vol, src = sampler.metrics_for_detection(det)
    
    logger.info(f"单独 DSM 提取结果：树高={h}m, 体积={vol}m³, 数据源={src}")
    assert src == "chm", "数据源应为 chm"
    assert h is not None and h > 0.0, "应正常估计出树高"
    assert vol is not None and vol > 0.0, "应估计出树冠体积"
    logger.info("单独 DSM 测试通过。")


def test_dsm_dem_mode():
    logger.info("============== 2. 测试 DSM + DEM 模式 ==============")
    rgb_geo = resolve_geo(IMAGE_PATH)
    
    sampler = build_chm_sampler(
        dsm_path=DSM_PATH,
        dem_path=DEM_PATH,
        rgb_geo=rgb_geo,
        stat="max",
    )
    assert sampler is not None, "DSM+DEM 模式构建 Sampler 失败"
    
    det = get_valid_test_det(rgb_geo)
    h, vol, src = sampler.metrics_for_detection(det)
    
    logger.info(f"DSM+DEM 提取结果：树高={h}m, 体积={vol}m³, 数据源={src}")
    assert h is not None and h > 0.0, "应正常估计出树高"
    assert vol is not None and vol > 0.0, "应估计出树冠体积"
    logger.info("DSM + DEM 混合模式测试通过。")


def test_las_point_cloud_mode():
    logger.info("============== 3. 测试 LiDAR 点云模式 ==============")
    if not os.path.exists(LAS_PATH):
        logger.warning(f"由于缺少点云测试数据 {LAS_PATH}，跳过该模式测试")
        return
        
    rgb_geo = resolve_geo(IMAGE_PATH)
    
    # 校验点云网格化分辨率默认值与可调参数
    sampler = build_chm_sampler(
        las_path=LAS_PATH,
        las_grid_size=0.1,  # 使用 0.1m 加快测试速度
        rgb_geo=rgb_geo,
        stat="max",
    )
    assert sampler is not None, "点云模式构建 Sampler 失败"
    
    det = get_valid_test_det(rgb_geo)
    
    h, vol, src = sampler.metrics_for_detection(det)
    logger.info(f"点云提取结果：树高={h}m, 体积={vol}m³, 数据源={src}")
    assert h is not None and h > 0.0, "点云树高应估计成功"
    assert vol is not None and vol > 0.0, "点云体积应估计成功"
    logger.info("LiDAR 点云模式测试通过。")


def test_db_migration_and_writing():
    logger.info("============== 4. 测试数据库热迁移与写入 ==============")
    # 1. 初始化内存数据库，验证表结构能跑通
    schema.init_db(TEST_DB_URL)
    logger.info("SQLite 内存数据库初始化及迁移成功")
    
    # 2. 模拟写入观测数据，检查新指标
    tract_id = writer.ensure_tract("20260623", "xuwen_beach", url=TEST_DB_URL, name="xuwen_test")
    run_id = "test_run_123"
    writer.start_run_log(run_id, "infer", url=TEST_DB_URL)
    
    # 构建包含高程与体积的 Detection
    det = Detection(x1=100.0, y1=100.0, x2=200.0, y2=200.0, score=0.88, label="casuarina")
    det.extra = {"height": 5.8, "height_source": "chm", "volume": 124.5}
    
    # 写入观测
    import rasterio
    with rasterio.open(IMAGE_PATH) as src:
        transform_obj = src.transform
        crs_obj = src.crs
    writer.write_observations(
        tract_id, run_id, [det],
        slice_size=1024, image_path=IMAGE_PATH,
        transform=transform_obj,
        crs=crs_obj,
        url=TEST_DB_URL
    )
    
    # 从 db 查询验证
    obs = reader.fetch_observations(run_id=run_id, url=TEST_DB_URL)
    assert len(obs) == 1, "应查出 1 条记录"
    saved = obs[0]
    logger.info(f"写入 observations 表结果验证：height={saved['height']}, crown_volume_geo={saved['crown_volume_geo']}")
    assert saved["height"] == 5.8
    assert saved["crown_volume_geo"] == 124.5
    
    # 3. 测试规范单木地块合并
    writer.consolidate_tract_trees(tract_id, run_id, obs, url=TEST_DB_URL)
    
    # 从 db 查询 tract_trees 验证
    conn = schema.resolve_db_path(TEST_DB_URL)
    import sqlite3
    db_conn = sqlite3.connect(conn)
    db_conn.row_factory = sqlite3.Row
    row = db_conn.execute("SELECT * FROM tract_trees WHERE tract_id=?", (tract_id,)).fetchone()
    db_conn.close()
    
    assert row is not None, "规范单木表应有一条记录"
    logger.info(f"写入 tract_trees 表结果验证：height={row['height']}, crown_volume_geo={row['crown_volume_geo']}")
    assert row["height"] == 5.8
    assert row["crown_volume_geo"] == 124.5
    logger.info("数据库热迁移与指标保存测试通过。")


if __name__ == "__main__":
    logger.info("🚀 启动徐闻多源高程及林业指标融合集成测试...")
    try:
        test_dsm_only_mode()
        test_dsm_dem_mode()
        test_las_point_cloud_mode()
        test_db_migration_and_writing()
        logger.info("🎉 所有集成测试用例全部通过！系统稳健性良好。")
    except Exception as e:
        logger.exception("测试执行中遇到异常：")
        sys.exit(1)
    finally:
        # 清理测试数据库文件
        db_file = Path("data/test_db.sqlite")
        if db_file.exists():
            try:
                db_file.unlink()
                logger.info("已清理临时测试数据库。")
            except OSError:
                pass
