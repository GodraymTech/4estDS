import unittest
import numpy as np
from pathlib import Path
import tempfile
from PIL import Image

from forestds.detect.base import BaseDetector, Detection, Detections, Window
from forestds.detect import get_detector
from forestds.engine.sources import InMemorySource, TiledDirectorySource
from forestds.engine.infer import run_inference, InferenceConfig


class MockDetector(BaseDetector):
    name = "mock"

    def load(self) -> None:
        self._loaded = True

    def predict(self, window: Window) -> Detections:
        # 在窗口中心点附近产生一个框
        cx = window.w / 2.0
        cy = window.h / 2.0
        return Detections([
            Detection(
                x1=cx - 10, y1=cy - 10,
                x2=cx + 10, y2=cy + 10,
                score=0.8,
                label="tree"
            )
        ])


class TestInferencePipeline(unittest.TestCase):
    def test_builtin_mock_detector_registry(self):
        detector = get_detector("mock")
        detector.ensure_loaded()

        dets = detector.predict(Window(x=0, y=0, w=100, h=100))

        self.assertEqual(detector.name, "mock")
        self.assertEqual(len(dets), 1)
        self.assertEqual(dets.items[0].label, "tree")

    def test_in_memory_source_direct(self):
        # 建立一个 100x100x3 的全黑图像数组
        array = np.zeros((100, 100, 3), dtype=np.uint8)
        source = InMemorySource(array)
        detector = MockDetector()
        
        config = InferenceConfig(
            root_size=100,
            overlap_rate=0.0,
            conf_thr=0.5,
            iou_thr=0.5
        )
        
        result = run_inference(source, detector, config)
        
        self.assertEqual(result.tiles_total, 1)
        self.assertEqual(result.tiles_processed, 1)
        self.assertEqual(len(result.detections), 1)
        
        # 验证检测框的坐标是否被平移还原回全图坐标
        det = result.detections.items[0]
        # 窗口在 (0,0) 长宽 100x100，中心在 (50, 50)，框应为 (40, 40, 60, 60)
        self.assertEqual(det.x1, 40.0)
        self.assertEqual(det.y1, 40.0)
        self.assertEqual(det.x2, 60.0)
        self.assertEqual(det.y2, 60.0)

    def test_tiled_directory_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            td = Path(tmpdir)
            # 生成形如 o{x}_{y}__s{tile_size}.jpg 的假文件
            # 文件1: 坐标 (0, 0), 大小 50x50
            f1 = td / "o0_0__s50.jpg"
            Image.new("RGB", (50, 50)).save(f1)
            # 文件2: 坐标 (30, 0), 大小 50x50
            f2 = td / "o30_0__s50.jpg"
            Image.new("RGB", (50, 50)).save(f2)
            
            source = TiledDirectorySource(td, width=80, height=50)
            detector = MockDetector()
            config = InferenceConfig(
                root_size=50,
                overlap_rate=0.2,
                conf_thr=0.5,
                iou_thr=0.5,
                center_merge_frac=0.1
            )
            
            result = run_inference(source, detector, config)
            
            self.assertEqual(result.tiles_total, 2)
            self.assertEqual(result.tiles_processed, 2)
            # 两个瓦片会分别检测出框，WBF 之后我们检查它们是否进行了合并或各自保留
            # 瓦片1中心在 (25, 25) -> 全图 (15, 15, 35, 35)
            # 瓦片2在 (30, 0)，中心在 (25, 25) -> 全图 (55, 15, 75, 35)
            self.assertEqual(len(result.detections), 2)


if __name__ == "__main__":
    unittest.main()
