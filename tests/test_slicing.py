"""创新点 A 核心算法单测(纯 Python,无重依赖)。"""
from fourestds.preprocess import slicing as S


def test_crown_px_size():
    assert S.crown_px_size(4.0, 0.1) == 40.0


def test_truncation_probability_bounds():
    # 目标远小于切片且 overlap 足够 -> 截断概率很小
    assert S.truncation_probability(40, 1024, 256) < 0.05
    # 目标不小于切片 -> 必截断
    assert S.truncation_probability(1024, 1024, 128) == 1.0
    # overlap 超过目标宽 -> 不截断
    assert S.truncation_probability(100, 1024, 200) == 0.0


def test_expected_truncation_monotonic_in_overlap():
    sizes = [40, 60, 80, 120]
    low = S.expected_truncation(sizes, 1024, 64)
    high = S.expected_truncation(sizes, 1024, 256)
    assert high <= low  # 重叠越大,截断越少


def test_optimize_tile_params_respects_detectability():
    # 小冠幅 -> 允许较小切片(T 不超可检测上限)
    p = S.optimize_tile_params(
        scale_px=40, model_input=1024, d_min_px=24, w_large_px=120,
        epsilon=0.05, lambda_cost=0.15,
    )
    t_max = 1024 * 40 / 24
    assert p.tile <= t_max
    assert p.exp_trunc <= 0.05 + 1e-9 or p.cost == float("inf")


def test_cluster_scales_basic():
    sizes = [20, 22, 21, 80, 82, 79, 200, 205]
    scales = S.cluster_scales(sizes, k=3)
    assert len(scales) == 3
    assert scales == sorted(scales)
    # 三个聚簇中心应大致落在 ~21 / ~80 / ~200
    assert 15 < scales[0] < 30
    assert 60 < scales[1] < 100
    assert 150 < scales[2] < 250


def test_integral_image_and_region_sum():
    mask = [
        [1, 1, 0],
        [1, 0, 0],
        [0, 0, 1],
    ]
    ii = S.integral_image(mask)
    assert S.region_sum(ii, 0, 0, 3, 3) == 4
    assert S.region_sum(ii, 2, 0, 1, 2) == 0  # 右上 2x1 全 nodata
    assert S.is_all_nodata(ii, 2, 0, 1, 2) is True
    assert S.is_all_nodata(ii, 0, 0, 2, 1) is False


def test_build_quadtree_single_scale_degenerates_to_grid():
    # 目标尺寸恒等于 root_size -> 不应细分,退化为均匀网格
    tiles = S.build_quadtree(
        width=2048, height=2048,
        target_size_fn=lambda cx, cy: 1024,
        root_size=1024, min_size=256,
    )
    assert all(t.size == 1024 for t in tiles)
    assert len(tiles) == 4


def test_build_quadtree_refines_small_targets():
    # 左半区域目标小 -> 细分;右半目标大 -> 不细分
    def target(cx, cy):
        return 200 if cx < 1024 else 1024

    tiles = S.build_quadtree(
        width=2048, height=2048,
        target_size_fn=target,
        root_size=1024, min_size=128,
    )
    small = [t for t in tiles if t.size < 1024]
    assert small, "左半应产生更小的切片"
    assert any(t.size == 1024 for t in tiles), "右半应保留大切片"


def test_clamp_window_in_bounds():
    assert S.clamp_window(0, 0, 1024, 2048, 2048) == (0, 0, 1024, 1024)


def test_clamp_window_border_overflow():
    # 右下边缘 tile 超出影像 -> 裁剪到有效读窗
    assert S.clamp_window(1800, 1800, 512, 2048, 2048) == (1800, 1800, 248, 248)


def test_clamp_window_fully_outside():
    x, y, w, h = S.clamp_window(5000, 5000, 512, 2048, 2048)
    assert w == 0 and h == 0


def test_clamp_window_invalid_size():
    assert S.clamp_window(0, 0, 0, 2048, 2048) == (0, 0, 0, 0)
