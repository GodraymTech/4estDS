import unittest
import numpy as np
from forestds.fusion.chm import CHMSampler
from forestds.detect.base import Detection
from forestds.geo import Affine

class TestCHMSampler(unittest.TestCase):
    def setUp(self):
        # Create a simple 10x10 CHM grid for testing
        self.chm = np.zeros((10, 10), dtype=np.float32)
        # Create a tree peak of height 5.0m
        self.chm[4, 4] = 5.0
        self.chm[4, 5] = 4.0
        self.chm[5, 4] = 3.0
        self.chm[5, 5] = 0.05 # below threshold of 0.1m
        
        # Identity transform (1 pixel = 1 meter)
        self.transform = Affine(1.0, 0.0, 0.0, 0.0, -1.0, 10.0)

    def test_sampler_with_real_canopy_enabled(self):
        sampler = CHMSampler(
            chm=self.chm,
            chm_transform=self.transform,
            rgb_transform=self.transform,
            chm_threshold=0.1,
            find_real_canopy=True,
            max_valid_height=8.0,
            volume_method="cbh",
            cbh_factor=0.3,
        )
        
        # Detection box covering the peak
        det = Detection(x1=3, y1=3, x2=6, y2=6, score=0.9, label="tree")
        res = sampler.metrics_for_detection(det)
        
        # Verify unified height (stat="max")
        self.assertEqual(res["height"], 5.0)
        
        # Verify split areas:
        # Est area is the full box area (3x3 = 9 pixels)
        self.assertEqual(res["crown_area_px_est"], 9.0)
        self.assertEqual(res["crown_area_geo_est"], 9.0)
        
        # Real area only counts pixels >= 0.1m (which are 5.0, 4.0, 3.0 -> 3 pixels)
        self.assertEqual(res["crown_area_px_real"], 3.0)
        self.assertEqual(res["crown_area_geo_real"], 3.0)
        
        # Verify split volumes:
        # vol_real should be calculated using cbh method on filtered pixels (height >= cbh)
        # cbh = 5.0 * 0.3 = 1.5m.
        # Filtered heights >= 1.5m are: 5.0, 4.0, 3.0.
        # Sum of (height - cbh) = (5.0-1.5) + (4.0-1.5) + (3.0-1.5) = 3.5 + 2.5 + 1.5 = 7.5.
        # Since pixel area is 1.0, vol_real = 7.5.
        self.assertAlmostEqual(res["volume_real"], 7.5)
        
        # vol_est uses cone geometric formula: 1/3 * pi * r^2 * h_crown
        # r = (3 + 3) / 4 = 1.5m.
        # h_crown = 5.0 - 1.5 = 3.5m.
        # vol_est = 1/3 * pi * 1.5^2 * 3.5 = 8.24668...
        self.assertAlmostEqual(res["volume_est"], 8.246680715673209)

    def test_sampler_with_real_canopy_disabled(self):
        sampler = CHMSampler(
            chm=self.chm,
            chm_transform=self.transform,
            rgb_transform=self.transform,
            chm_threshold=0.1,
            find_real_canopy=False,
            max_valid_height=8.0,
            volume_method="cbh",
            cbh_factor=0.3,
        )
        
        det = Detection(x1=3, y1=3, x2=6, y2=6, score=0.9, label="tree")
        res = sampler.metrics_for_detection(det)
        
        # When find_real_canopy is False, real metrics copy est metrics
        self.assertEqual(res["crown_area_px_real"], res["crown_area_px_est"])
        self.assertEqual(res["crown_area_geo_real"], res["crown_area_geo_est"])
        self.assertEqual(res["volume_real"], res["volume_est"])

    def test_sampler_max_valid_height_cap(self):
        # Tree of height 15m (above cap of 8m)
        self.chm[4, 4] = 15.0
        
        # Capping is done at build time, let's simulate build time minimum capping:
        capped_chm = np.minimum(self.chm, 8.0)
        
        sampler = CHMSampler(
            chm=capped_chm,
            chm_transform=self.transform,
            rgb_transform=self.transform,
            chm_threshold=0.1,
            find_real_canopy=True,
            max_valid_height=8.0,
            max_height=20.0,
            volume_method="cbh",
            cbh_factor=0.3,
        )
        
        det = Detection(x1=3, y1=3, x2=6, y2=6, score=0.9, label="tree")
        res = sampler.metrics_for_detection(det)
        
        # Unified height should be capped at 8.0m
        self.assertEqual(res["height"], 8.0)

    def test_filter_vertical_outlier_gap(self):
        from forestds.fusion.chm import filter_vertical_outlier_gap
        
        # 模拟一棵 0.6m 的幼树，但在 1.55m 处悬浮了 2 个竹竿/孤立高点
        normal_crown_h = np.linspace(0.2, 0.6, 20)
        outlier_h = np.array([1.50, 1.55])
        all_h = np.concatenate([normal_crown_h, outlier_h])
        
        filtered = filter_vertical_outlier_gap(all_h, gap_threshold=0.35)
        self.assertEqual(len(filtered), 20)
        self.assertAlmostEqual(float(np.max(filtered)), 0.6)

        # 连续的大树高度点云，不应发生误截断
        continuous_tree_h = np.linspace(0.3, 3.5, 30)
        not_filtered = filter_vertical_outlier_gap(continuous_tree_h, gap_threshold=0.35)
        self.assertEqual(len(not_filtered), 30)
        self.assertAlmostEqual(float(np.max(not_filtered)), 3.5)

    def test_impute_canopy_mask(self):
        from forestds.fusion.chm import impute_canopy_mask
        
        # 创建一个带有内部空隙(欠采样孔洞)的二值树冠掩模
        mask = np.array([
            [0, 1, 1, 1, 0],
            [1, 1, 0, 1, 1],  # (1, 2) 是内部孔洞
            [1, 1, 1, 1, 1],
            [0, 1, 1, 1, 0],
            [0, 0, 0, 0, 0],  # 裸泥地
        ], dtype=bool)
        
        imputed = impute_canopy_mask(mask)
        # 内部空洞 (1, 2) 应被填补
        self.assertTrue(imputed[1, 2])
        # 外部纯泥地 (4, 4) 绝不扩张
        self.assertFalse(imputed[4, 4])
        self.assertFalse(imputed[0, 0])
        self.assertEqual(np.sum(imputed), np.sum(mask) + 1)

    def test_filter_macro_ground_points(self):
        from forestds.fusion.chm import filter_macro_ground_points
        
        # 模拟平坦泥滩(高程约 0.92m)，其中部分区域长有杂草(高程 1.25m)
        np.random.seed(42)
        n_mud = 150
        n_grass = 50
        gx = np.random.uniform(0, 8, n_mud + n_grass)
        gy = np.random.uniform(0, 8, n_mud + n_grass)
        
        # 泥面点高程在 0.90 ~ 0.94m
        gz_mud = np.random.normal(0.92, 0.01, n_mud)
        # 草丛反射高程在 1.20 ~ 1.30m
        gz_grass = np.random.normal(1.25, 0.02, n_grass)
        gz = np.concatenate([gz_mud, gz_grass]).astype(np.float32)
        
        filtered_coords, filtered_z = filter_macro_ground_points(
            gx, gy, gz, macro_sz=10.0, p_low=10.0, max_diff=0.12
        )
        
        # 草丛反射假地面点应被有效剔除，滤波后地面最高点不应超过 1.05m
        self.assertLess(float(np.max(filtered_z)), 1.05)
        self.assertGreater(len(filtered_z), 100)

    def test_sampler_with_gap_filter_and_imputation(self):
        # 构造包含断层竹竿与内部采样孔洞的 CHM
        chm = np.zeros((10, 10), dtype=np.float32)
        # 正常树冠主体 3x3 (高 0.6m，中心 (4, 4) 有一处无采样点 0.0)
        chm[3, 3] = 0.5
        chm[3, 4] = 0.6
        chm[3, 5] = 0.5
        chm[4, 3] = 0.6
        chm[4, 4] = 0.0  # 欠采样漏孔
        chm[4, 5] = 0.6
        chm[5, 3] = 0.5
        chm[5, 4] = 0.6
        chm[5, 5] = 0.5
        # 孤立悬空竹竿 (高 1.55m，位于框内 (2, 3))
        chm[2, 3] = 1.55
        
        sampler = CHMSampler(
            chm=chm,
            chm_transform=self.transform,
            rgb_transform=self.transform,
            chm_threshold=0.1,
            find_real_canopy=True,
            filter_vertical_gap=True,
            vertical_gap_threshold=0.35,
            impute_canopy_holes=True,
        )
        
        det = Detection(x1=2, y1=2, x2=7, y2=7, score=0.9, label="tree")
        res = sampler.metrics_for_detection(det)
        
        # 树高应当被截断滤波至 0.6m，而不是 1.55m
        self.assertAlmostEqual(res["height"], 0.6)
        # 树冠内部 (4, 4) 孔洞应被弥合，有效像元数应从 8 恢复为 9 (且不包含截断的竹竿)
        self.assertEqual(res["crown_area_px_real"], 9.0)


if __name__ == "__main__":
    unittest.main()

