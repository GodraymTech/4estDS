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
