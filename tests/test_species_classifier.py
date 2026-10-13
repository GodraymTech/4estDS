import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from forestds.detect.base import Detection
from forestds.detect.classifier import (
    SpeciesClassifier,
    refine_species_with_classifier,
)

# 与 configs/default.yaml 中 classify.species_map 保持一致
SPECIES_MAP = {
    "QQ": "秋茄",
    "HHL": "红海榄",
    "THS": "桐花树",
    "ML": "木榄",
    "BGR": "白骨壤",
    "WBHS": "无瓣海桑",
    "TREE": "红树",
    "GG": "枯木",
}


def _make_classifier(**overrides) -> SpeciesClassifier:
    kwargs = {
        "species_map": SPECIES_MAP,
        "conf_threshold": 0.25,
        "batch_size": 128,
    }
    kwargs.update(overrides)
    return SpeciesClassifier("unused.pt", **kwargs)


class TestSpeciesClassifier(unittest.TestCase):
    def test_species_map_requires_tree_fallback(self):
        with self.assertRaises(ValueError):
            SpeciesClassifier(
                "unused.pt",
                species_map={"QQ": "秋茄"},
                conf_threshold=0.25,
                batch_size=128,
            )

    def test_predict_crops_feeds_bgr_to_model(self):
        clf = _make_classifier()
        clf._model = MagicMock()
        clf._model.predict.return_value = []

        rgb = np.zeros((8, 8, 3), dtype=np.uint8)
        rgb[..., 0] = 255  # 纯红（RGB 第 0 通道）

        clf.predict_crops([rgb])

        fed = clf._model.predict.call_args[0][0][0]
        np.testing.assert_array_equal(fed, rgb[..., ::-1])

    def test_refine_species_logic_with_mock(self):
        # 模拟 3 个检测框：2 个 TREE，1 个 GG
        dets = [
            Detection(x1=10, y1=10, x2=50, y2=50, score=0.9, label="TREE"),
            Detection(x1=60, y1=60, x2=90, y2=90, score=0.85, label="TREE"),
            Detection(x1=100, y1=100, x2=140, y2=140, score=0.8, label="GG"),
        ]

        mock_classifier = MagicMock(spec=SpeciesClassifier)
        mock_classifier.species_map = dict(SPECIES_MAP)
        mock_classifier.predict_crops.return_value = [
            ("秋茄", 0.95),
            ("红树", 0.88),
        ]

        with patch("forestds.engine.sources.RasterImageSource") as mock_source_cls:
            mock_source = MagicMock()
            mock_source.width = 200
            mock_source.height = 200
            mock_source.read_window.return_value = np.zeros((40, 40, 3), dtype=np.uint8)
            mock_source_cls.return_value.__enter__.return_value = mock_source

            counts = refine_species_with_classifier(
                dets,
                image_path="dummy.tif",
                settings={"classify.pad_ratio": 0.1},
                classifier=mock_classifier,
            )

        self.assertEqual(dets[0].label, "QQ")
        self.assertEqual(dets[0].extra.get("cls_score"), 0.95)
        self.assertEqual(dets[1].label, "TREE")
        self.assertEqual(dets[1].extra.get("cls_score"), 0.88)
        self.assertEqual(dets[2].label, "GG")  # GG 框不受分类器影响
        self.assertEqual(counts, {"QQ": 1, "TREE": 1, "GG": 1})

    def test_refine_species_with_pad_ratio(self):
        dets = [
            Detection(x1=20, y1=20, x2=40, y2=40, score=0.9, label="TREE"),
        ]
        mock_classifier = MagicMock(spec=SpeciesClassifier)
        mock_classifier.species_map = dict(SPECIES_MAP)
        mock_classifier.predict_crops.return_value = [("QQ", 0.9)]

        with patch("forestds.engine.sources.RasterImageSource") as mock_source_cls:
            mock_source = MagicMock()
            mock_source.width = 100
            mock_source.height = 100
            mock_source.read_window.return_value = np.zeros((24, 24, 3), dtype=np.uint8)
            mock_source_cls.return_value.__enter__.return_value = mock_source

            # w=20, h=20，pad_ratio=0.1 -> pad=2，读窗为 [18, 18, 24, 24]
            refine_species_with_classifier(
                dets,
                image_path="dummy.tif",
                settings={"classify.pad_ratio": 0.1},
                classifier=mock_classifier,
            )

            mock_source.read_window.assert_called_once_with(18, 18, 24, 24)

    def test_refine_without_classify_config_raises(self):
        dets = [Detection(x1=0, y1=0, x2=10, y2=10, score=0.9, label="TREE")]
        with self.assertRaises(ValueError):
            refine_species_with_classifier(
                dets,
                image_path="dummy.tif",
                settings={"classify.pad_ratio": 0.1},
            )

    def test_real_model_inference_if_available(self):
        model_path = Path(".4estDS/models/m03-yolo11l-7cls-SOTA.pt")
        test_img = Path("data/for_test/多源数据研究_徐闻/DOM/xuwen_1024px.jpg")
        if not model_path.exists() or not test_img.exists():
            self.skipTest("权重或测试图像不存在，跳过真实模型推理单测")

        classifier = SpeciesClassifier(
            str(model_path),
            species_map=SPECIES_MAP,
            conf_threshold=0.25,
            batch_size=128,
        )
        crop = np.zeros((64, 64, 3), dtype=np.uint8)
        preds = classifier.predict_crops([crop])
        self.assertEqual(len(preds), 1)
        label, conf = preds[0]
        self.assertIn(label, set(SPECIES_MAP.keys()))
        self.assertIsInstance(conf, float)


if __name__ == "__main__":
    unittest.main()
