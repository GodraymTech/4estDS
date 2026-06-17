from fourestds.postprocess import wbf


def test_iou_identical():
    assert wbf.iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0


def test_iou_disjoint():
    assert wbf.iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0


def test_wbf_merges_overlapping():
    boxes = [(0, 0, 10, 10), (1, 1, 11, 11), (100, 100, 110, 110)]
    scores = [0.9, 0.8, 0.7]
    fused_boxes, fused_scores = wbf.weighted_boxes_fusion(boxes, scores, iou_thr=0.5)
    assert len(fused_boxes) == 2  # 前两个融合,第三个独立
    assert len(fused_scores) == 2


def test_wbf_empty():
    assert wbf.weighted_boxes_fusion([], []) == ([], [])


def test_fuse_label_aware_keeps_species_separate():
    # 位置重叠但标签不同 -> 不应被当成重复
    boxes = [(0, 0, 10, 10), (1, 1, 11, 11)]
    scores = [0.9, 0.8]
    same = wbf.fuse(boxes, scores, labels=["mangrove", "mangrove"], iou_thr=0.5)
    diff = wbf.fuse(boxes, scores, labels=["mangrove", "avicennia"], iou_thr=0.5)
    assert len(same) == 1
    assert len(diff) == 2
    assert same[0].label == "mangrove"
    assert same[0].support == 2


def test_fuse_conf_type_max_vs_avg():
    boxes = [(0, 0, 10, 10), (1, 1, 11, 11)]
    scores = [0.9, 0.5]
    avg = wbf.fuse(boxes, scores, iou_thr=0.5, conf_type="avg")
    mx = wbf.fuse(boxes, scores, iou_thr=0.5, conf_type="max")
    assert abs(avg[0].score - 0.7) < 1e-9
    assert abs(mx[0].score - 0.9) < 1e-9


def test_fuse_weight_pulls_coords_to_reliable_box():
    # 两框高度重叠;第二框权重极低 -> 融合坐标应靠近第一框
    boxes = [(0.0, 0.0, 10.0, 10.0), (2.0, 2.0, 12.0, 12.0)]
    scores = [0.9, 0.9]
    weighted = wbf.fuse(boxes, scores, weights=[1.0, 0.01], iou_thr=0.3)
    assert len(weighted) == 1
    assert weighted[0].box[0] < 0.5  # x1 被拉向可靠框


def test_fuse_center_merge_catches_boundary_split():
    # 两个低 IoU 但中心极近的框(跨边界切半) -> center_merge 可合为一
    boxes = [(0, 0, 10, 10), (8, 0, 18, 10)]
    scores = [0.8, 0.8]
    no_merge = wbf.fuse(boxes, scores, iou_thr=0.5)
    merged = wbf.fuse(boxes, scores, iou_thr=0.5, center_merge_frac=0.7)
    assert len(no_merge) == 2
    assert len(merged) == 1
