"""阶段八单测:跨时相匹配(医牛利)与生命周期追踪。

纯 assert,无 pytest 依赖;由 scripts/smoke.py / 手动 importlib 运行 test_* 函数。
"""
from fourestds.lifecycle import (
    Individual,
    TreeRecord,
    build_cost_matrix,
    linear_sum_assignment,
    match_trees,
    track_sequence,
)


def test_hungarian_optimal_known_matrix():
    # 最优解应为 (0->1)+(1->0)+(2->2)=1+2+2=5
    cost = [[4, 1, 3], [2, 0, 5], [3, 2, 2]]
    rows, cols = linear_sum_assignment(cost)
    total = sum(cost[i][j] for i, j in zip(rows, cols))
    assert total == 5, total
    assert sorted(rows) == [0, 1, 2]
    assert sorted(cols) == [0, 1, 2]


def test_hungarian_rectangular_more_cols():
    # 2 行 3 列:只能配 2 对,选最小
    cost = [[1, 9, 9], [9, 9, 2]]
    rows, cols = linear_sum_assignment(cost)
    assert len(rows) == 2
    total = sum(cost[i][j] for i, j in zip(rows, cols))
    assert total == 3, total


def test_hungarian_rectangular_more_rows():
    # 3 行 2 列:只能配 2 对(转置路径)
    cost = [[1, 9], [9, 2], [5, 5]]
    rows, cols = linear_sum_assignment(cost)
    assert len(rows) == 2
    total = sum(cost[i][j] for i, j in zip(rows, cols))
    assert total == 3, total


def test_hungarian_empty():
    assert linear_sum_assignment([]) == ([], [])
    assert linear_sum_assignment([[]]) == ([], [])


def test_cost_matrix_gating():
    a = [TreeRecord("a", 0, 0)]
    b = [TreeRecord("x", 0, 0), TreeRecord("y", 100, 100)]
    cm = build_cost_matrix(a, b, max_dist=3.0)
    assert cm[0][0] < 1.0          # 重合位置,代价极小
    assert cm[0][1] >= 1e9          # 超门控,禁止


def test_match_basic_birth_and_match():
    prev = [TreeRecord("a", 0, 0, height=5, crown=4), TreeRecord("b", 10, 10, height=8, crown=6)]
    curr = [
        TreeRecord("x", 0.5, 0.3, height=5.4, crown=4.2),
        TreeRecord("y", 10.2, 9.8, height=8.5, crown=6.1),
        TreeRecord("z", 50, 50, height=3, crown=2),
    ]
    res = match_trees(prev, curr, max_dist=3.0)
    assert set(res.pairs) == {(0, 0), (1, 1)}
    assert res.births == [2]       # z 新生
    assert res.deaths == []


def test_match_death_when_disappears():
    prev = [TreeRecord("a", 0, 0), TreeRecord("b", 10, 10)]
    curr = [TreeRecord("x", 0.2, 0.1)]
    res = match_trees(prev, curr, max_dist=3.0)
    assert res.pairs == [(0, 0)]
    assert res.deaths == [1]       # b 枯死/遗漏
    assert res.births == []


def test_match_uses_height_to_disambiguate():
    # 两个 curr 均在门控内且位置近似,靠树高区分
    prev = [TreeRecord("a", 0, 0, height=5.0)]
    curr = [TreeRecord("tall", 0.6, 0, height=20.0), TreeRecord("near", 0.7, 0, height=5.1)]
    res = match_trees(prev, curr, max_dist=3.0, w_pos=0.2, w_height=2.0)
    assert res.pairs == [(0, 1)]   # 应匹配树高接近的 near


def test_track_sequence_growth_and_lifecycle():
    # 3 时相:t1 树A、树B;t2 两棵都在且长高,新增树C;t3 树B消失(枯死)
    snaps = [
        ("202301", [TreeRecord("A1", 0, 0, height=3.0, crown=2.0), TreeRecord("B1", 20, 20, height=5.0, crown=3.0)]),
        ("202401", [TreeRecord("A2", 0.3, 0.2, height=4.0, crown=2.5), TreeRecord("B2", 20.1, 19.9, height=5.5, crown=3.2), TreeRecord("C2", 40, 40, height=2.0, crown=1.0)]),
        ("202501", [TreeRecord("A3", 0.5, 0.1, height=5.2, crown=3.0), TreeRecord("C3", 40.2, 39.8, height=3.0, crown=1.5)]),
    ]
    res = track_sequence(snaps, location_cluster="st8", max_dist=3.0)
    # 3 个独立个体:A(贯穿3期)、B(2期后枯死)、C(2期)
    assert res.n_individuals == 3, res.n_individuals
    by_first = {ind.first_seen: ind for ind in res.individuals}
    a = next(i for i in res.individuals if len(i.growth) == 3)
    assert a.first_seen == "202301" and a.last_seen == "202501"
    assert a.status == "alive"
    rate = a.height_growth_rate()
    assert rate is not None and rate > 0   # 树A 持续长高
    # 树B 应被标记枯死
    dead = [i for i in res.individuals if i.status == "dead"]
    assert len(dead) == 1
    assert dead[0].last_seen == "202401"
    assert res.n_deaths == 1


def test_individual_growth_json():
    ind = Individual(individual_id="ind_x_1", location_cluster="x", first_seen="202301", last_seen="202401")
    from fourestds.lifecycle import GrowthPoint
    ind.growth = [GrowthPoint("202301", height=3.0, crown=2.0), GrowthPoint("202401", height=5.0, crown=3.0)]
    gj = ind.to_growth_json()
    assert gj["n_observations"] == 2
    assert abs(gj["height_growth_rate"] - 2.0) < 1e-6
    assert len(gj["points"]) == 2
