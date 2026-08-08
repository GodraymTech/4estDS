"""ultralytics 结果解析与图像通道工具(yolo12 / rtdetr 共用)。

把 ultralytics 的单图 Results 解析为本项目的 Detections(读窗内部坐标)。
不在模块顶层 import torch/numpy,保证未装重依赖时导入不报错。
"""
from __future__ import annotations

from ..base import Detection, Detections


def ensure_bgr(pixels):
    """把输入图像（无论 4 通道 RGBA/NIR、单通道、2 维灰度等）统一转换为连续的 (H, W, 3) BGR uint8 数组供 ultralytics 使用。"""
    if pixels is None:
        return None
    import numpy as np
    arr = pixels if isinstance(pixels, np.ndarray) else np.asarray(pixels)
    if arr.ndim == 4:
        arr = arr[0]
    if arr.ndim == 2:
        arr = np.repeat(arr[:, :, None], 3, axis=2)
    elif arr.ndim == 3:
        if arr.shape[0] in (1, 2, 3, 4, 5, 8) and arr.shape[0] < min(arr.shape[1], arr.shape[2]):
            arr = arr.transpose(1, 2, 0)
        if arr.shape[2] == 1:
            arr = np.repeat(arr, 3, axis=2)
        elif arr.shape[2] >= 4:
            arr = arr[:, :, :3]
        elif arr.shape[2] == 2:
            arr = np.pad(arr, ((0, 0), (0, 0), (0, 1)), mode="edge")
        # RGB to BGR
        arr = arr[:, :, ::-1]

    if arr.dtype != np.uint8:
        if np.issubdtype(arr.dtype, np.floating):
            max_val = float(np.nanmax(arr)) if arr.size else 1.0
            if max_val <= 1.0:
                arr = (np.clip(arr, 0, 1) * 255.0).astype(np.uint8)
            else:
                arr = np.clip(arr, 0, 255).astype(np.uint8)
        elif arr.dtype in (np.uint16, np.int16, np.uint32, np.int32):
            max_val = float(np.max(arr)) if arr.size else 255.0
            if max_val > 255.0:
                arr = np.clip(arr / (max_val / 255.0), 0, 255).astype(np.uint8)
            else:
                arr = np.clip(arr, 0, 255).astype(np.uint8)
        else:
            arr = np.clip(arr, 0, 255).astype(np.uint8)

    return np.ascontiguousarray(arr)


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
