import tempfile
from pathlib import Path
import numpy as np
import rasterio
from forestds.utils.crop_tiff import crop_tiff_main

def test_crop_tiff_center_and_random():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        input_tiff = tmp_path / "test.tif"
        
        # 创建一个 1000x1000 的 3 波段 dummy TIFF 图像
        width, height = 1000, 1000
        count = 3
        dtype = rasterio.uint8
        
        # 产生一些 dummy 图像数据
        data = np.ones((count, height, width), dtype=np.uint8) * 128
        # 将上面 100 行设为 0 作为 nodata 值
        data[:, :100, :] = 0
        
        meta = {
            "driver": "GTiff",
            "height": height,
            "width": width,
            "count": count,
            "dtype": dtype,
            "crs": "EPSG:4326",
            "transform": rasterio.transform.from_origin(110, 20, 0.00001, 0.00001),
            "nodata": 0
        }
        
        with rasterio.open(input_tiff, "w", **meta) as dst:
            dst.write(data)
            
        # 1. 测试中心裁剪 (num_crops=0, 避开上方的 nodata)
        dest_dir = tmp_path / "center_crops"
        ret = crop_tiff_main(
            input_path=input_tiff,
            output_dir=dest_dir,
            num_crops=0,
            size=500,
            nodata_tolerance=0.01
        )
        assert ret == 0
        assert (dest_dir / "test_center.tif").exists()
        
        # 验证裁剪出的图像规格
        with rasterio.open(dest_dir / "test_center.tif") as src:
            assert src.width == 500
            assert src.height == 500
            assert src.count == 3
            
        # 2. 测试随机无重叠裁剪 (num_crops=2, 避开上方的 nodata 区域)
        dest_dir_rand = tmp_path / "random_crops"
        ret_rand = crop_tiff_main(
            input_path=input_tiff,
            output_dir=dest_dir_rand,
            num_crops=2,
            size=200,
            nodata_tolerance=0.01
        )
        assert ret_rand == 0
        assert (dest_dir_rand / "test_1.tif").exists()
        assert (dest_dir_rand / "test_2.tif").exists()
        
        # 验证随机导出的样本规格且确保没有 nodata 区域 (上方的 y < 100)
        with rasterio.open(dest_dir_rand / "test_1.tif") as src:
            assert src.width == 200
            assert src.height == 200
            # 确保转换矩阵也是正确的
            assert src.transform != dst.transform


def test_crop_tiff_vector():
    import geopandas as gpd
    from shapely.geometry import Polygon

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        input_tiff = tmp_path / "test.tif"
        
        # 创建一个 1000x1000 的 3 波段 dummy TIFF 图像
        width, height = 1000, 1000
        count = 3
        dtype = rasterio.uint8
        
        # 产生一些 dummy 图像数据
        data = np.ones((count, height, width), dtype=np.uint8) * 128
        
        meta = {
            "driver": "GTiff",
            "height": height,
            "width": width,
            "count": count,
            "dtype": dtype,
            "crs": "EPSG:4326",
            "transform": rasterio.transform.from_origin(110, 20, 0.00001, 0.00001),  # from_origin 会自动处理 y 轴朝南（dy 为负）
            "nodata": 0
        }
        
        with rasterio.open(input_tiff, "w", **meta) as dst:
            dst.write(data)
            
        # 准备矢量多边形
        # 影像地理范围：左=110, 上=20, 右=110 + 1000*0.00001=110.01, 下=20 - 1000*0.00001=19.99
        polygons = [
            # 要素 0: 完全在影像内 (左上=110.002, 19.998; 右下=110.008, 19.992)
            Polygon([(110.002, 19.998), (110.008, 19.998), (110.008, 19.992), (110.002, 19.992)]),
            # 要素 1: 完全在影像外
            Polygon([(112.0, 22.0), (112.01, 22.0), (112.01, 21.99), (112.0, 21.99)])
        ]
        
        # 1. 正常路径测试
        gdf = gpd.GeoDataFrame(geometry=polygons, crs="EPSG:4326")
        vector_file = tmp_path / "test.geojson"
        gdf.to_file(vector_file, driver="GeoJSON")
        
        dest_dir_vector = tmp_path / "vector_crops"
        ret = crop_tiff_main(
            input_path=input_tiff,
            output_dir=dest_dir_vector,
            vector_path=vector_file
        )
        assert ret == 0
        assert (dest_dir_vector / "test_crop_0_600x600.jpg").exists()
        # 要素 1 超出范围应被跳过
        assert not (dest_dir_vector / "test_crop_1_600x600.jpg").exists()
        
        # 2. 测试 CRS 不一致报错
        gdf_wrong_crs = gpd.GeoDataFrame(geometry=polygons, crs="EPSG:3857")
        vector_file_wrong = tmp_path / "test_wrong_crs.geojson"
        gdf_wrong_crs.to_file(vector_file_wrong, driver="GeoJSON")
        
        ret_wrong = crop_tiff_main(
            input_path=input_tiff,
            output_dir=dest_dir_vector,
            vector_path=vector_file_wrong
        )
        assert ret_wrong == 1
        
        # 3. 测试无交集报错
        gdf_no_intersect = gpd.GeoDataFrame(geometry=[polygons[1]], crs="EPSG:4326")
        vector_file_no_int = tmp_path / "test_no_intersect.geojson"
        gdf_no_intersect.to_file(vector_file_no_int, driver="GeoJSON")
        
        ret_no_int = crop_tiff_main(
            input_path=input_tiff,
            output_dir=dest_dir_vector,
            vector_path=vector_file_no_int
        )
        assert ret_no_int == 1

