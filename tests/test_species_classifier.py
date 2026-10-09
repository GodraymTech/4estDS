import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from forestds.detect.base import Detection
from forestds.detect.classifier import (
    DEFAULT_SPECIES_MAP,
    SpeciesClassifier,
    refine_species_with_classifier,
)


class TestSpeciesClassifier(unittest.TestCase):
    def test_default_species_map(self):
        self.assertEqual(DEFAULT_SPECIES_MAP["QQ"], "秋茄")
        self.assertEqual(DEFAULT_SPECIES_MAP["HHL"], "红海榄")
        self.assertEqual(DEFAULT_SPECIES_MAP["THS"], "桐花树")
        self.assertEqual(DEFAULT_SPECIES_MAP["ML"], "木榄")
        self.assertEqual(DEFAULT_SPECIES_MAP["BGR"], "白骨壤")
        self.assertEqual(DEFAULT_SPECIES_MAP["WBHS"], "无瓣海桑")
        self.assertEqual(DEFAULT_SPECIES_MAP["TREE"], "OTHER")
        self.assertEqual(DEFAULT_SPECIES_MAP["GG"], "GG")

    def test_refine_species_logic_with_mock(self):
        # 模拟 3 个检测框：2 个 TREE，1 个 GG
        dets = [
            Detection(x1=10, y1=10, x2=50, y2=50, score=0.9, label="TREE"),
            Detection(x1=60, y1=60, x2=90, y2=90, score=0.85, label="TREE"),
            Detection(x1=100, y1=100, x2=140, y2=140, score=0.8, label="GG"),
        ]

        # 构造 Mock 分类器
        mock_classifier = MagicMock(spec=SpeciesClassifier)
        mock_classifier.species_map = dict(DEFAULT_SPECIES_MAP)
        # 第一次返回 QQ (秋茄)，第二次返回 TREE (OTHER)
        mock_classifier.predict_crops.return_value = [
            ("秋茄", 0.95),
            ("OTHER", 0.88),
        ]

        # 模拟从影像中读取窗口像素
        with patch("forestds.engine.sources.RasterImageSource") as mock_source_cls:
            mock_source = MagicMock()
            mock_source.width = 200
            mock_source.height = 200
            mock_source.read_window.return_value = np.zeros((40, 40, 3), dtype=np.uint8)
            mock_source_cls.return_value.__enter__.return_value = mock_source

            counts = refine_species_with_classifier(
                dets,
                image_path="dummy.tif",
                classifier=mock_classifier,
            )

        # 验证结果
        self.assertEqual(dets[0].label, "秋茄")
        self.assertEqual(dets[0].extra.get("cls_score"), 0.95)
        self.assertEqual(dets[1].label, "OTHER")
        self.assertEqual(dets[1].extra.get("cls_score"), 0.88)
        self.assertEqual(dets[2].label, "GG")  # GG 框不受分类器影响
        self.assertEqual(counts, {"秋茄": 1, "OTHER": 1, "GG": 1})

    def test_refine_species_with_pad_ratio(self):
        dets = [
            Detection(x1=20, y1=20, x2=40, y2=40, score=0.9, label="TREE"),
        ]
        mock_classifier = MagicMock(spec=SpeciesClassifier)
        mock_classifier.species_map = dict(DEFAULT_SPECIES_MAP)
        mock_classifier.predict_crops.return_value = [("秋茄", 0.9)]

        with patch("forestds.engine.sources.RasterImageSource") as mock_source_cls:
            mock_source = MagicMock()
            mock_source.width = 100
            mock_source.height = 100
            mock_source.read_window.return_value = np.zeros((24, 24, 3), dtype=np.uint8)
            mock_source_cls.return_value.__enter__.return_value = mock_source

            # settings 传入 pad_ratio = 0.1，w=20, h=20，pad=2，因此读窗为 [18, 18, 24, 24]
            mock_settings = {"classify.pad_ratio": 0.1}
            refine_species_with_classifier(
                dets,
                image_path="dummy.tif",
                settings=mock_settings,
                classifier=mock_classifier,
            )

            # 验证 read_window 调用的坐标为 (18, 18, 24, 24)
            mock_source.read_window.assert_called_once_with(18, 18, 24, 24)

    def test_real_model_inference_if_available(self):
        model_path = Path(".4estDS/models/m03-yolo11l-7cls-SOTA.pt")
        test_img = Path("data/for_test/多源数据研究_徐闻/DOM/xuwen_1024px.jpg")
        if not model_path.exists() or not test_img.exists():
            self.skipTest("权重或测试图像不存在，跳过真实模型推理单测")

        classifier = SpeciesClassifier(weights=str(model_path), conf_threshold=0.25)
        crop = np.zeros((64, 64, 3), dtype=np.uint8)
        preds = classifier.predict_crops([crop])
        self.assertEqual(len(preds), 1)
        label, conf = preds[0]
        self.assertIn(label, list(DEFAULT_SPECIES_MAP.values()) + ["OTHER"])
        self.assertIsInstance(conf, float)


if __name__ == "__main__":
    unittest.main()
