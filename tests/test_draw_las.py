from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import numpy as np
from rasterio.transform import Affine

from forestds.utils.draw_las import draw_las_main


def test_draw_las_main_invalid_path():
    # 验证输入路径不存在时能优雅退出并返回 1
    res = draw_las_main("non_existent_cloud.las", "non_existent_dom.tif")
    assert res == 1


def test_draw_las_main_non_existent_dom(tmp_path):
    # 验证 LAS 存在但 DOM 不存在时返回 1
    dummy_las = tmp_path / "dummy.las"
    dummy_las.write_bytes(b"dummy")
    
    res = draw_las_main(str(dummy_las), "non_existent_dom.tif")
    assert res == 1


def test_draw_las_main_success(tmp_path):
    # 验证 LAS 存在且 DOM 存在时，正常运行逻辑并生成图像/矢量
    # 1. 模拟点云数据
    mock_las = MagicMock()
    mock_las.points = [1, 2, 3]
    mock_las.x = np.array([10.0, 11.0, 12.0])
    mock_las.y = np.array([20.0, 21.0, 22.0])
    mock_las.z = np.array([5.0, 6.0, 7.0])
    mock_las.classification = np.array([2, 1, 2], dtype=np.uint8)
    
    # 2. 模拟 DOM 数据 (有 3 个 RGB 通道，其中有一些非零像素避免被判定为全是黑边)
    mock_dom = MagicMock()
    mock_dom.width = 100
    mock_dom.height = 100
    mock_dom.transform = Affine(1.0, 0.0, 0.0, 0.0, -1.0, 30.0)
    mock_dom.crs = "EPSG:4326"
    # np.ones 确保有效像素大于 5，能通过 valid_mask 校验
    mock_dom.read.return_value = np.ones((3, 100, 100), dtype=np.uint8) * 10
    mock_dom.xy.side_effect = lambda r, c: (float(c), float(30 - r))

    # 3. 创建真实的临时占位文件以通过 pathlib.exists() 校验
    las_file = tmp_path / "cloud.las"
    dom_file = tmp_path / "dom.tif"
    las_file.write_text("dummy")
    dom_file.write_text("dummy")
    
    # 4. Patch 相关第三方接口，避免真实读写磁盘和耗时绘图
    with patch("laspy.read", return_value=mock_las), \
         patch("rasterio.open", return_value=MagicMock(__enter__=MagicMock(return_value=mock_dom))), \
         patch("matplotlib.pyplot.savefig") as mock_save, \
         patch("geopandas.GeoDataFrame.to_file") as mock_shp_save:
         
        res = draw_las_main(str(las_file), str(dom_file), profile_width=0.5, threshold=0.1)
        assert res == 0
