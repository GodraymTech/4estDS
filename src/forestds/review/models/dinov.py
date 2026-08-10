"""DINOv Visual In-Context Prompt 适配器。"""
from __future__ import annotations

import logging
import math
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

import cv2
import numpy as np
import torch
from PIL import Image
from torchvision import transforms

from ..domain import ReviewValidationError
from .base import PromptContext, RasterWindow, ReviewPrediction

log = logging.getLogger(__name__)

# 将 dinov_core 路径（位于 .4estDS/models/dinov/dinov_core 或本地缓存）加入模块查找
def _ensure_core_path() -> Path:
    candidates = [
        Path(".4estDS/models/dinov/dinov_core"),
        Path.home() / ".4estDS/models/dinov/dinov_core",
        Path(__file__).parent / "dinov_core",
    ]
    for c in candidates:
        if c.is_dir():
            path_str = str(c.resolve())
            if path_str not in sys.path:
                sys.path.insert(0, path_str)
            return c.resolve()
    return candidates[0].resolve()


def _clean_rgb(img: Any) -> np.ndarray:
    """确保输入图像恒为标准 (H, W, 3) uint8 连续 RGB。"""
    if not isinstance(img, np.ndarray):
        img = np.asarray(img)
    if img.ndim == 4:
        img = img[0]
    if img.ndim == 2:
        img = np.repeat(img[:, :, None], 3, axis=2)
    elif img.ndim == 3:
        if img.shape[0] in (1, 2, 3, 4, 5, 8) and img.shape[0] < min(img.shape[1], img.shape[2]):
            img = img.transpose(1, 2, 0)
        if img.shape[2] == 1:
            img = np.repeat(img, 3, axis=2)
        elif img.shape[2] >= 4:
            img = img[:, :, :3]
        elif img.shape[2] == 2:
            img = np.pad(img, ((0, 0), (0, 0), (0, 1)), mode="edge")

    if img.dtype != np.uint8:
        if np.issubdtype(img.dtype, np.floating):
            max_val = float(np.nanmax(img)) if img.size else 1.0
            if max_val <= 1.0:
                img = (np.clip(img, 0, 1) * 255.0).astype(np.uint8)
            else:
                img = np.clip(img, 0, 255).astype(np.uint8)
        else:
            img = np.clip(img, 0, 255).astype(np.uint8)

    return np.ascontiguousarray(img)


def _inverse_sigmoid(x: torch.Tensor, eps: float = 1e-5) -> torch.Tensor:
    x = x.clamp(min=0, max=1)
    return torch.log(x.clamp(min=eps) / (1 - x).clamp(min=eps))


class DINOvReviewAdapter:
    """基于 DINOv (Visual In-Context Prompting) 的交互式复核模型适配器。"""

    def __init__(
        self,
        weights: str | Path,
        *,
        config_path: str | Path | None = None,
        device: str | None = None,
        conf: float = 0.50,
        imgsz: int = 640,
        model_factory: Callable[..., Any] | None = None,
    ):
        self.weights = _resolve_model_path(weights)
        self.config_path = _resolve_model_path(config_path or "configs/dinov/dinov_sam_coco_train.yaml")
        self.device = device or ("cuda:0" if torch.cuda.is_available() else "cpu")
        self.conf = float(conf)
        self.imgsz = int(imgsz)
        self.model_factory = model_factory
        self.model: Any = None

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": "dinov",
            "text_prompt": False,
            "visual_prompt": True,
            "segmentation": True,
            "weights": str(self.weights),
            "available": self.weights.is_file(),
        }

    def load(self) -> None:
        if self.model is not None:
            return
        if not self.weights.is_file():
            raise ReviewValidationError(
                f"DINOv 权重文件不存在: {self.weights}",
                code="review_model_missing",
                details={"path": str(self.weights)},
            )
        if self.model_factory is not None:
            self.model = self.model_factory(str(self.weights))
            return

        try:
            import importlib

            _ensure_core_path()
            dinov_mod = importlib.import_module("dinov")
            base_model_mod = importlib.import_module("dinov.BaseModel")
            args_mod = importlib.import_module("utils.arguments")

            build_model = dinov_mod.build_model
            BaseModel = base_model_mod.BaseModel
            load_opt_from_config_file = args_mod.load_opt_from_config_file

            opt = load_opt_from_config_file(str(self.config_path))
            opt["WEIGHT"] = str(self.weights)
            opt["device"] = self.device
            base_model = BaseModel(opt, build_model(opt)).from_pretrained(str(self.weights))
            base_model = base_model.eval().to(self.device)
            self.model = base_model
            log.info("DINOv 模型加载完成 (device=%s, weights=%s)", self.device, self.weights)
        except Exception as exc:
            raise ReviewValidationError(f"加载 DINOv 失败: {exc}", code="review_model_load_failed") from exc

    def prepare_text_prompts(self, prompts: Sequence[dict[str, Any]]) -> PromptContext:
        raise ReviewValidationError("DINOv 专为视觉 Prompt 设计，文本 Prompt 请使用 YOLO-World 或 YOLOE。", code="unsupported_text_prompt")

    def prepare_visual_prompts(
        self,
        reference_image: Any,
        bboxes: Any,
        classes: Any,
        category_ids: Sequence[str] | None = None,
    ) -> PromptContext:
        self.load()
        boxes = np.asarray(bboxes, dtype=float).reshape(-1, 4)
        labels = np.asarray(classes, dtype=int).reshape(-1)
        if len(boxes) == 0 or len(boxes) != len(labels):
            raise ReviewValidationError("视觉 Prompt 需要等量的参考框和 class ID。", code="invalid_visual_prompt")
        class_ids = list(category_ids or [str(value) for value in sorted(set(labels.tolist()))])
        ref_clean = _clean_rgb(reference_image)

        # 提取参考图特征与 Query 特征
        try:
            h_ref, w_ref = ref_clean.shape[:2]
            mask_np = np.zeros((h_ref, w_ref, 1), dtype=np.uint8)
            for b in boxes:
                x1, y1, x2, y2 = max(0, int(b[0])), max(0, int(b[1])), min(w_ref, int(b[2])), min(h_ref, int(b[3]))
                mask_np[y1:y2, x1:x2, 0] = 255

            pil_ref = Image.fromarray(ref_clean)
            pil_mask = Image.fromarray(mask_np.squeeze(-1))

            resize_transform = transforms.Resize(self.imgsz, interpolation=Image.BICUBIC)
            img_ref_resized = resize_transform(pil_ref)
            mask_ref_resized = resize_transform(pil_mask)

            w_rz, h_rz = img_ref_resized.size
            t_ref = torch.from_numpy(np.asarray(img_ref_resized).copy()).permute(2, 0, 1).to(self.device).float()
            mask_arr = np.asarray(mask_ref_resized)[:, :, None].copy()
            t_mask = torch.from_numpy(mask_arr).permute(2, 0, 1).to(self.device).float()

            data_ref = {
                "image": t_ref,
                "height": h_rz,
                "width": w_rz,
                "targets": [{"rand_shape": t_mask, "pb": torch.tensor([1.0]).to(self.device)}],
            }

            with torch.inference_mode():
                feat_ref_ms, _, padded_h, padded_w = self.model.model.get_encoder_feature([data_ref])
                query_label, query_bbox, attn_mask = self.model.model.get_visual_prompt_content_feature(
                    feat_ref_ms, data_ref["targets"][0]["rand_shape"], padded_h, padded_w
                )

            embedding_data = {
                "query_label": query_label,
                "attn_mask": attn_mask,
                "padded_h": padded_h,
                "padded_w": padded_w,
            }
        except Exception as exc:
            log.warning("DINOv 提取参考特征失败: %s", exc)
            embedding_data = None

        return PromptContext(
            mode="visual",
            class_ids=class_ids,
            reference_image=ref_clean,
            reference_boxes=boxes.tolist(),
            reference_classes=[int(x) for x in labels.tolist()],
            embedding=embedding_data,
            encoded=True if embedding_data is not None else False,
        )

    def predict_batch(self, windows: Sequence[RasterWindow], prompt_context: PromptContext) -> list[ReviewPrediction]:
        if not windows or not prompt_context.embedding:
            return []
        self.load()

        predictions: list[ReviewPrediction] = []
        embed = prompt_context.embedding
        query_label = embed["query_label"]
        attn_mask = embed["attn_mask"]
        padded_h = embed["padded_h"]
        padded_w = embed["padded_w"]

        point_coords = torch.ones(1, 4, device=self.device, dtype=torch.float)
        point_coords[:, :2] = 0.0
        query_bbox_init = _inverse_sigmoid(point_coords[None])

        resize_transform = transforms.Resize(self.imgsz, interpolation=Image.BICUBIC)

        with torch.inference_mode():
            for win in windows:
                img_rgb = _clean_rgb(win.pixels)
                h_orig, w_orig = img_rgb.shape[:2]
                pil_tgt = Image.fromarray(img_rgb)
                img_tgt_resized = resize_transform(pil_tgt)
                w_tgt_rz, h_tgt_rz = img_tgt_resized.size
                t_tgt = torch.from_numpy(np.asarray(img_tgt_resized).copy()).permute(2, 0, 1).to(self.device).float()
                data_tgt = {"image": t_tgt, "height": h_tgt_rz, "width": w_tgt_rz}

                feat_tgt_ms, mask_feat_tgt, _, _ = self.model.model.get_encoder_feature([data_tgt])
                masks, ious, ori_masks, scores = self.model.model.evaluate_demo_content_openset_multi_with_content_features(
                    [data_tgt], mask_feat_tgt, feat_tgt_ms, query_label,
                    query_bbox_init, attn_mask, padded_h, padded_w
                )

                for idx in range(len(scores)):
                    score = float(scores[idx].cpu())
                    if score < self.conf:
                        continue
                    mask_bin = (masks[idx].cpu().numpy() > 0.0).astype(np.uint8)
                    mask_orig = cv2.resize(mask_bin, (w_orig, h_orig), interpolation=cv2.INTER_NEAREST)
                    if mask_orig.sum() < 4:
                        continue

                    # 从 Mask 提取外接矩形与轮廓
                    contours, _ = cv2.findContours(mask_orig, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    if not contours:
                        continue
                    bx, by, bw, bh = cv2.boundingRect(contours[0])

                    # 业务规则过滤：单木树冠在遥感切片中不会占满整个切片（剔除 DETR 全局大背景 Query）
                    if bw > 0.65 * w_orig and bh > 0.65 * h_orig:
                        continue

                    category = prompt_context.class_ids[0] if prompt_context.class_ids else "tree"

                    predictions.append(ReviewPrediction(
                        box_px=[
                            float(bx + win.x),
                            float(by + win.y),
                            float(bx + bw + win.x),
                            float(by + bh + win.y),
                        ],
                        score=score,
                        category_id=category,
                    ))

        return predictions


def _resolve_model_path(value: str | Path) -> Path:
    raw = Path(value).expanduser()
    if raw.is_absolute():
        return raw
    candidates = [Path.cwd() / raw]
    candidates.extend(parent / raw for parent in Path.cwd().parents)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()
