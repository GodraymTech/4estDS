"""ultralytics 结果解析与图像通道工具(yolo12 / rtdetr 共用)。

把 ultralytics 的单图 Results 解析为本项目的 Detections(读窗内部坐标)。
不在模块顶层 import torch/numpy,保证未装重依赖时导入不报错。
"""
from __future__ import annotations

from ..base import Detection, Detections


def ensure_bgr(pixels):
    """把 RGB (H,W,3) 数组转 BGR 供 ultralytics(cv2 习惯)使用。

    约定 image_source 读出的窗口像素为 RGB;ultralytics 对 numpy 输入按 BGR 处理,
    故此处反转通道。非 3 通道(灰度/多光谱)原样返回;None 返回 None。
    """
    if pixels is None:
        return None
    arr = pixels
    try:
        if getattr(arr, "ndim", None) == 3 and arr.shape[2] == 3:
            return arr[:, :, ::-1]
    except Exception:
        pass
    return arr


def _to_numpy(t):
    """将 torch.Tensor / numpy 统一为 numpy(CPU)。"""
    if t is None:
        return None
    if hasattr(t, "detach"):
        t = t.detach()
    if hasattr(t, "cpu"):
        t = t.cpu()
    if hasattr(t, "numpy"):
        return t.numpy()
    return t


def build_detections_from_result(result, *, backend: str) -> Detections:
    """把 ultralytics 单图结果解析为 Detections(读窗内部坐标)。

    兼容 YOLO 与 RT-DETR:两者 result.boxes 都提供 xyxy/conf/cls。
    """
    items: list[Detection] = []
    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return Detections(items, {"backend": backend})
    names = getattr(result, "names", {}) or {}
    xyxy = _to_numpy(getattr(boxes, "xyxy", None))
    confs = _to_numpy(getattr(boxes, "conf", None))
    clss = _to_numpy(getattr(boxes, "cls", None))
    if xyxy is None:
        return Detections(items, {"backend": backend})
    for i in range(len(xyxy)):
        x1, y1, x2, y2 = (float(v) for v in xyxy[i][:4])
        score = float(confs[i]) if confs is not None else 0.0
        cls_id = int(clss[i]) if clss is not None else 0
        if isinstance(names, dict):
            label = names.get(cls_id, str(cls_id))
        else:
            label = str(cls_id)
        items.append(
            Detection(x1, y1, x2, y2, score=score, label=label, extra={"cls_id": cls_id})
        )
    return Detections(items, {"backend": backend})
