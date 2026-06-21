"""切片清单推理编排器(阶段三)。

流程:
  1) 用创新点 A 的四叉树生成 tile 清单(纯几何,查 size_map 表)。
  2) 逐 tile: clamp_window 裁到边界 -> 跳空读窗 -> 检测器推理(读窗内部坐标)。
  3) detections.offset(x, y) 回写全图坐标。
  4) 全图 WBF 去重(跨 tile / 跨尺度重复检出)。

设计要点(中间产物谨慎):不落地裁切图片;读窗按需从 image_source 取像素。
mock 后端不需像素,可在无 GPU/无网环境端到端验证。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..detect.base import BaseDetector, Detection, Detections, Window
from loguru import logger as log
from ..postprocess.wbf import fuse
from ..preprocess.slicing import generate_slice_windows



@dataclass
class InferenceResult:
    detections: Detections
    tiles_total: int = 0
    tiles_processed: int = 0
    tiles_skipped_empty: int = 0
    raw_count: int = 0
    fused_count: int = 0
    meta: dict = field(default_factory=dict)


def run_inference(
    image_source,
    detector: BaseDetector,
    *,
    target_size_fn=None,
    root_size: int = 1024,
    min_size: int = 256,
    conf_thr: float = 0.25,
    iou_thr: float = 0.55,
    batch_size: int = 8,
    overlap_rate: float = 0.2,
    conf_type: str = "max",
    trunc_penalty: float = 0.5,
) -> InferenceResult:
    """对一幅影像跑完整的切片->推理->去重流程。

    image_source: 需有 width/height 属性,可选 read_window(x,y,w,h)。
    """
    width = int(image_source.width)
    height = int(image_source.height)
    if width <= 0 or height <= 0:
        log.warning("空影像: width={} height={}, 跳过推理", width, height)
        return InferenceResult(Detections([]), meta={"empty_image": True})

    t0 = time.perf_counter()
    log.info(
        "推理开始: 影像 {}x{} backend={} root_size={} overlap_rate={:.2%} conf_thr={:.2f} iou_thr={:.2f} conf_type={}",
        width, height, getattr(detector, "name", "?"), root_size, overlap_rate, conf_thr, iou_thr, conf_type,
    )

    # 1. 规则切片网格生成，全权交给预处理公共模块
    coords = generate_slice_windows(width, height, root_size, overlap_rate)
    skipped = 0

    log.info(
        "切片清单: 生成并有效读窗 {} tile, 跳过空窗 {} ",
        len(coords), skipped, overlap_rate,
    )

    detector.ensure_loaded()
    read = getattr(image_source, "read_window", None)
    global_items: list[Detection] = []
    processed = 0
    bs = max(1, batch_size)
    
    from tqdm import tqdm
    
    # 分批推理:每批只读取该批读窗像素,内存占用以 batch_size 为界
    with tqdm(total=len(coords), desc="动态读窗推理中", leave=False, ncols=80) as pbar:
        for i in range(0, len(coords), bs):
            chunk = coords[i : i + bs]
            windows = [
                Window(
                    x=x, y=y, w=w, h=h,
                    pixels=read(x, y, w, h) if callable(read) else None,
                )
                for (x, y, w, h) in chunk
            ]
            for win, dets in zip(windows, detector.predict_batch(windows)):
                filtered_dets = dets.filter_score(conf_thr).items
                log.debug("滑窗 (x={}, y={}, w={}, h={}) 检测数 {} ", win.x, win.y, win.w, win.h, len(filtered_dets))
                for d in filtered_dets:
                    # 在读窗内部坐标判断是否触及“内部边界”(非图像边缘)->可能被切断
                    trunc = (
                        (d.x1 <= 1.0 and win.x > 0)
                        or (d.y1 <= 1.0 and win.y > 0)
                        or (d.x2 >= win.w - 1.0 and win.x + win.w < width)
                        or (d.y2 >= win.h - 1.0 and win.y + win.h < height)
                    )
                    gd = d.offset(win.x, win.y)
                    gd.extra = {
                        **gd.extra,
                        "truncated": bool(trunc),
                        "box_px_sub": [d.x1, d.y1, d.x2, d.y2],
                        "source_subimage_path": f"Window_{win.x}_{win.y}_{win.w}_{win.h}"
                    }
                    global_items.append(gd)
                processed += 1
            pbar.update(len(chunk))

    raw_count = len(global_items)
    # 标签感知 + 权重感知 WBF:截断框降权(完整框主导融合坐标),保留物种标签
    boxes = [d.as_box() for d in global_items]
    scores = [d.score for d in global_items]
    labels = [d.label for d in global_items]
    weights = [
        d.score * (trunc_penalty if d.extra.get("truncated") else 1.0)
        for d in global_items
    ]
    fused_boxes = fuse(
        boxes, scores,
        labels=labels, weights=weights,
        iou_thr=iou_thr, conf_type=conf_type,
    )
    fused = Detections(
        [
            Detection(
                x1=f.box[0], y1=f.box[1], x2=f.box[2], y2=f.box[3],
                score=f.score, label=f.label,
                extra={
                    "support": f.support,
                    **global_items[f.extra["best_index"]].extra
                },
            )
            for f in fused_boxes
        ],
        {"backend": getattr(detector, "name", "?"), "fusion": "wbf"},
    )
    elapsed = time.perf_counter() - t0
    dedup = (1 - len(fused) / raw_count) * 100 if raw_count else 0.0
    log.info(
        "推理完成: tiles={} detected_tiles={} skipped_tiles={} num_bboxes={} -> {} (-{:.1f}%) cost={:.2f}s",
        len(coords), processed, skipped, raw_count, len(fused), dedup, elapsed,
    )
    return InferenceResult(
        detections=fused,
        tiles_total=len(coords),
        tiles_processed=processed,
        tiles_skipped_empty=skipped,
        raw_count=raw_count,
        fused_count=len(fused),
        meta={"width": width, "height": height, "tile_size": root_size},
    )


def run_image_inference(
    image_path: str,
    detector: BaseDetector,
    *,
    slice_action: str = "slice",
    seed_window_size: int = 2560,
    overlap_rate: float | None = None,
    settings = None,
    run_id: str = "infer",
) -> InferenceResult:
    """自动判定影像格式与配置，并执行对应路由模式的滑窗或整图推理，最终输出统一的 InferenceResult。"""
    import os
    import re
    from pathlib import Path
    from PIL import Image
    import numpy as np
    from tqdm import tqdm
    
    from .. import paths
    from ..detect import get_detector
    from ..detect.base import Window, Detections, Detection
    from ..postprocess.wbf import fuse

    from ..preprocess import prepare_inference_image
    
    # 提取公共后处理配置项 (读取 settings 或回退默认值)
    if settings is None:
        from ..config import load_settings
        settings = load_settings()
        
    trunc_penalty = float(settings.get("postprocess.trunc_penalty", 0.5))
    conf_type = str(settings.get("postprocess.conf_type", "max"))
    center_merge_frac = float(settings.get("postprocess.center_merge_frac", 0.0))
    iou_thr = float(settings.get("detect.iou_threshold", 0.6))
    conf_thr = float(settings.get("detect.conf_threshold", 0.25))

    # 1. 委托预处理模块执行所有前置逻辑 (读尺寸、检查COG、自适应寻优、静态切片落盘)
    prep = prepare_inference_image(
        image_path=image_path,
        slice_action=slice_action,
        seed_window_size=seed_window_size,
        overlap_rate=overlap_rate,
        settings=settings,
        run_id=run_id,
        detector=detector,
    )
    
    width = prep["width"]
    height = prep["height"]
    mode = prep["mode"]
    t_size = prep["tile_size"]
    r_ov = prep["overlap_rate"]
    tiles_dir = prep["tiles_dir"]
    image_path = prep["image_path"]

    # ---- 模式一: 静态切片落盘推理 ----
    if mode == "physical_slice":
        tile_files = sorted(list(tiles_dir.glob("*.jpg")))
        tiles_total = len(tile_files)
        log.info("开始推理【已落盘切片目录】...")
        
        detector.ensure_loaded()
        global_detections = []
        batch_size = int(settings.get("detect.batch_size", 16))
        
        for idx in tqdm(range(0, len(tile_files), batch_size), desc="推理中", ncols=80):
            batch_files = tile_files[idx : idx + batch_size]
            windows = []
            
            for f in batch_files:
                m = re.match(r"o(\d+)_(\d+)__s(\d+)", f.stem)
                if not m:
                    continue
                wx, wy, t_sz = int(m.group(1)), int(m.group(2)), int(m.group(3))
                
                try:
                    with Image.open(f) as img:
                        pixels = np.asarray(img.convert("RGB"))
                        h_t, w_t = pixels.shape[:2]
                        # 物理瓦片本来就是原生防越界的，所以直接以图片实际物理宽高大小读取，绝不二次裁剪！
                        win = Window(x=wx, y=wy, w=w_t, h=h_t, pixels=pixels)
                        win.source_subimage_path = str(f)
                        windows.append(win)
                except Exception as e:
                    log.warning("读取瓦片 {} 失败: {}", f.name, e)
                    
            if not windows:
                continue
                
            results_batch = detector.predict_batch(windows)
            for win, dets in zip(windows, results_batch):
                filtered_dets = dets.filter_score(conf_thr).items
                sub_path = getattr(win, "source_subimage_path", None)
                
                for d in filtered_dets:
                    gd = d.offset(win.x, win.y)
                    # 碰边判定
                    trunc = (
                        (d.x1 <= 1.0 and win.x > 0)
                        or (d.y1 <= 1.0 and win.y > 0)
                        or (d.x2 >= win.w - 1.0 and win.x + win.w < width)
                        or (d.y2 >= win.h - 1.0 and win.y + win.h < height)
                    )
                    gd.extra = {
                        **gd.extra,
                        "truncated": bool(trunc),
                        "box_px_sub": [d.x1, d.y1, d.x2, d.y2],
                        "source_subimage_path": sub_path
                    }
                    global_detections.append(gd)

        # 3.4 全图 WBF 去重融合
        log.info("原始检测框共 {} 个，进行加权框融合 (WBF)...", len(global_detections))
        boxes = [d.as_box() for d in global_detections]
        scores = [d.score for d in global_detections]
        labels = [d.label for d in global_detections]
        weights = [
            d.score * (trunc_penalty if d.extra.get("truncated") else 1.0)
            for d in global_detections
        ]
        fused_boxes = fuse(
            boxes, scores,
            labels=labels, weights=weights,
            iou_thr=iou_thr, conf_type=conf_type,
            center_merge_frac=center_merge_frac
        )
        fused_detections = Detections(
            [
                Detection(
                    x1=f.box[0], y1=f.box[1], x2=f.box[2], y2=f.box[3],
                    score=f.score, label=f.label,
                    extra={
                        "support": f.support,
                        **global_detections[f.extra["best_index"]].extra
                    }
                )
                for f in fused_boxes
            ],
            {"backend": getattr(detector, "name", "?"), "fusion": "wbf"}
        )
        raw_n = len(global_detections)
        fused_n = len(fused_detections)
        dedup_rate = (1.0 - fused_n / raw_n) * 100.0 if raw_n > 0 else 0.0
        log.info(
            "WBF 去重融合完成: 原始框={} -> 融合框={}，去重率={:.1f}%",
            raw_n, fused_n, dedup_rate
        )
        # 获取 tiles_dir 相对于 home_dir() 的路径
        from .. import paths
        rel_tiles_dir = None
        if tiles_dir:
            try:
                rel_tiles_dir = str(tiles_dir.relative_to(paths.home_dir()))
            except Exception:
                rel_tiles_dir = str(tiles_dir)
                
        return InferenceResult(
            detections=fused_detections,
            tiles_total=tiles_total,
            tiles_processed=tiles_total,
            tiles_skipped_empty=0,
            raw_count=len(global_detections),
            fused_count=len(fused_detections),
            meta={"width": width, "height": height, "tiles_dir": rel_tiles_dir, "tile_size": t_size}
        )

    # ---- 模式二: COG 动态滑窗推理 ----
    elif mode == "on_the_fly":
        log.info("开始推理【COG在线切片】...")
        from .sources import RasterImageSource
        source = RasterImageSource(image_path)
        try:
            return run_inference(
                source, detector,
                root_size=t_size,
                min_size=int(settings.get("min_size", 256)),
                conf_thr=conf_thr,
                iou_thr=iou_thr,
                overlap_rate=r_ov,
                conf_type=conf_type,
                trunc_penalty=trunc_penalty,
                batch_size=int(settings.get("detect.batch_size", 16)),
            )
        finally:
            source.close()

    # ---- 模式三: 整图直接推理 ----
    else:
        log.info("开始推理【整图不切】: {} ({}x{})", image_path, width, height)
        detector.ensure_loaded()
        with Image.open(image_path) as img:
            pixels = np.asarray(img.convert("RGB"))
            
        win = Window(x=0, y=0, w=width, h=height, pixels=pixels)
        dets = detector.predict(win)
        
        filtered_dets = dets.filter_score(conf_thr)
        for d in filtered_dets.items:
            d.extra = {
                **d.extra,
                "box_px_sub": [d.x1, d.y1, d.x2, d.y2],
                "source_subimage_path": image_path
            }
        log.debug("检测到 {} 个原始目标", len(filtered_dets))
        
        return InferenceResult(
            detections=filtered_dets,
            tiles_total=1,
            tiles_processed=1,
            tiles_skipped_empty=0,
            raw_count=len(filtered_dets),
            fused_count=len(filtered_dets),
            meta={"width": width, "height": height, "tile_size": None}
        )
