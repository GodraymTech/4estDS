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

if __name__ == "__main__":
    unittest.main()
