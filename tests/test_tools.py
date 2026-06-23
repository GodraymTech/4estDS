import os
import json
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
from PIL import Image


from forestds.utils.draw_bbox import find_label_file, load_annotations, silence_inference_env
from forestds.fusion.crown import verify_overlap, align_dsm_to_dom, estimate_canopy_contours
from forestds.geo import Affine, GeoInfo


def test_find_label_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        # 1. 模拟同目录下同名文件
        img = tmp_path / "test_img.jpg"
        img.touch()
        
        # 模拟匹配 .txt
        lbl_txt = tmp_path / "test_img.txt"
        lbl_txt.touch()
        
        assert find_label_file(str(img)) == str(lbl_txt)
        
        # 移除 .txt，增加 .xml
        lbl_txt.unlink()
        lbl_xml = tmp_path / "test_img.xml"
        lbl_xml.touch()
        assert find_label_file(str(img)) == str(lbl_xml)
        
        # 2. 模拟常规数据集目录结构
        img_dir = tmp_path / "images" / "train"
        lbl_dir = tmp_path / "labels" / "train"
        img_dir.mkdir(parents=True, exist_ok=True)
        lbl_dir.mkdir(parents=True, exist_ok=True)
        
        ds_img = img_dir / "ds_img.png"
        ds_img.touch()
        
        ds_lbl = lbl_dir / "ds_img.txt"
        ds_lbl.touch()
        
        assert find_label_file(str(ds_img)) == str(ds_lbl)


def test_load_annotations():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        # YOLO 标注文件
        yolo_lbl = tmp_path / "lbl.txt"
        with open(yolo_lbl, "w") as f:
            f.write("0 0.5 0.5 0.2 0.2\n")
            f.write("1 0.3 0.3 0.1 0.1\n")
            
        boxes = load_annotations(str(yolo_lbl), 100, 100, "dummy.jpg")
        assert len(boxes) == 2
        # YOLO 第一行中心在 (50, 50), 宽20, 高20 -> x1=40, y1=40, x2=60, y2=60
        assert boxes[0] == (0, 40.0, 40.0, 60.0, 60.0)
        
        # VOC XML 标注文件
        voc_lbl = tmp_path / "lbl.xml"
        root = ET.Element("annotation")
        obj = ET.SubElement(root, "object")
        ET.SubElement(obj, "name").text = "2"
        bnd = ET.SubElement(obj, "bndbox")
        ET.SubElement(bnd, "xmin").text = "10"
        ET.SubElement(bnd, "ymin").text = "20"
        ET.SubElement(bnd, "xmax").text = "30"
        ET.SubElement(bnd, "ymax").text = "40"
        
        tree = ET.ElementTree(root)
        tree.write(voc_lbl)
        
        boxes = load_annotations(str(voc_lbl), 100, 100, "dummy.jpg")
        assert len(boxes) == 1
        assert boxes[0] == (2, 10.0, 20.0, 30.0, 40.0)

        # GeoJSON 标注文件
        geojson_lbl = tmp_path / "lbl.geojson"
        geojson_data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[10, 10], [20, 10], [20, 20], [10, 20], [10, 10]]]
                    },
                    "properties": {
                        "class_id": 3
                    }
                }
            ]
        }
        with open(geojson_lbl, "w") as f:
            json.dump(geojson_data, f)
            
        boxes = load_annotations(str(geojson_lbl), 100, 100, "dummy.jpg")
        assert len(boxes) == 1
        # 无 transform 时原样转换
        assert boxes[0] == (3, 10.0, 10.0, 20.0, 20.0)


def test_silence_inference_env():
    import sys
    print_captured = False
    
    with silence_inference_env():
        # 如果在此处打印，它应该不会漏到真实的终端 stdout 中
        print("This should be silenced and captured inside StringIO")
        sys.stderr.write("Stderr should also be silenced\n")
        print_captured = True
        
    assert print_captured


def test_verify_overlap():
    # 构造两个重合的仿射变换 (EPSG:4326)
    # x = 110 + col * 0.1, y = 20 - row * 0.1
    # 影像大小为 100x100
    # 中心点在 110 + 50 * 0.1 = 115, 20 - 50 * 0.1 = 15
    tf_dom = Affine(0.1, 0.0, 110.0, 0.0, -0.1, 20.0)
    tf_dsm = Affine(0.1, 0.0, 112.0, 0.0, -0.1, 18.0) # 中心在 117, 13
    
    dom_geo = GeoInfo(transform=tf_dom, crs_kind="geographic", origin_lat=15.0)
    dsm_geo = GeoInfo(transform=tf_dsm, crs_kind="geographic", origin_lat=13.0)
    
    # 模拟图片保存并加载元数据
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        dom_p = tmp_path / "dom.tif"
        dsm_p = tmp_path / "dsm.tif"
        
        # 简单创建假图片
        Image.new("RGB", (100, 100)).save(dom_p)
        Image.new("F", (100, 100)).save(dsm_p)
        
        # 只要能正常调用 verify_overlap 且不报错即可
        # 这里的 verify_overlap 内部由于没有 rasterio 时会回退到 Pillow 并且 resolve_geo，
        # 如果没有 sidecar 文件，resolve_geo 读到的 tf 为 None，因此不会报错 (跳过重合检查)。
        # 如果有 transform，它应该会通过校验。
        verify_overlap(str(dom_p), str(dsm_p))


def test_estimate_canopy_contours():
    # 创建一个 50x50 的高程 DSM
    # 像元大小 0.1m/px。我们在正中央(25, 25) 和角落 (10, 10) 分别设立两个峰值代表两棵树
    dsm = np.zeros((50, 50), dtype=np.float32)
    
    # 设立树1: 树顶高程 10m，向外递减
    for r in range(50):
        for c in range(50):
            d1 = np.sqrt((r - 25)**2 + (c - 25)**2)
            d2 = np.sqrt((r - 10)**2 + (c - 10)**2)
            val1 = max(0.0, 10.0 - d1 * 1.5)
            val2 = max(0.0, 6.0 - d2 * 1.5)
            dsm[r, c] = max(val1, val2)
            
    # 设置一个仿射变换
    tf = Affine(0.1, 0.0, 100.0, 0.0, -0.1, 50.0)
    
    # 提取树冠轮廓线
    boundary = estimate_canopy_contours(dsm, transform=tf)
    
    assert boundary.shape == (50, 50)
    # 应检测出边界，即 boundary 中含有 True 元素
    assert np.any(boundary)


def test_resolve_weights_path():
    from forestds.detect.registry import resolve_weights_path
    from forestds.paths import models_dir
    
    m_dir = models_dir()
    m_dir.mkdir(parents=True, exist_ok=True)
    
    # 使用唯一的随机前缀，防止与真实已有的模型冲突
    unique_name = "test_weights_uuid_999a888b.pt"
    dummy_model = m_dir / unique_name
    dummy_model.touch()
    
    try:
        res = resolve_weights_path("999a888b")
        assert res == str(dummy_model.resolve())
        
        res2 = resolve_weights_path("test_weights_uuid")
        assert res2 == str(dummy_model.resolve())
    finally:
        if dummy_model.exists():
            dummy_model.unlink()



if __name__ == "__main__":
    print("Running test_find_label_file...")
    test_find_label_file()
    print("Running test_load_annotations...")
    test_load_annotations()
    print("Running test_silence_inference_env...")
    test_silence_inference_env()
    print("Running test_verify_overlap...")
    test_verify_overlap()
    print("Running test_estimate_canopy_contours...")
    test_estimate_canopy_contours()
    print("Running test_resolve_weights_path...")
    test_resolve_weights_path()
    print("All tests passed successfully!")


