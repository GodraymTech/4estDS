from fourestds.lifecycle import distance, match_nearest


def test_distance():
    assert distance((0, 0), (3, 4)) == 5.0


def test_match_nearest_pairs_close_trees():
    prev = [(0, 0), (100, 100)]
    curr = [(1, 1), (101, 99), (500, 500)]
    pairs = match_nearest(prev, curr, max_dist=5)
    assert (0, 0) in pairs
    assert (1, 1) in pairs
    # (500,500) 未匹配 -> 新生
    matched_curr = {j for _, j in pairs}
    assert 2 not in matched_curr


def test_match_nearest_respects_threshold():
    prev = [(0, 0)]
    curr = [(100, 100)]
    assert match_nearest(prev, curr, max_dist=5) == []
