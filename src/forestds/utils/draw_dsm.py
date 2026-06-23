"""命令行 draw-dsm 辅助工具实现。

职责：
  - 验证 DOM 与 DSM 存在空间重叠（调用 verify_overlap）。
  - 执行 DOM 与 DSM 的空间重投影对齐。
  - 调用 fusion.crown 模块中基于分水岭与极值的核心数学算法提取冠幅边缘。
  - 将生成的边界矩阵与 DOM 原图像像素进行半透明青色通道混合。
  - 保存结果图片至缓存目录，文件名携带时间戳前缀，并包含自适应缩放机制防 OOM。
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image
from loguru import logger as log

from ..fusion.crown import verify_overlap, align_dsm_to_dom, estimate_canopy_contours


def draw_dsm_main(image_path: str, dsm_path: str) -> int:
    """draw-dsm 命令主要逻辑实现。"""
    from .. import paths
    paths.ensure_home()
    
    img_path = Path(image_path)
    dsm_p = Path(dsm_path)
    
    if not img_path.exists():
        log.error("找不到正射影像 DOM: {}", image_path)
        return 1
    if not dsm_p.exists():
        log.error("找不到高程影像 DSM: {}", dsm_path)
        return 1

    # 1. 验证 DOM 与 DSM 是否存在包含性地理重合
    try:
        verify_overlap(image_path, dsm_path)
    except ValueError as e:
        log.error("[tool.draw-dsm] 地理包含性检查失败: {}", e)
        return 1

    # 2. 空间重投影对齐
    log.info("[tool.draw-dsm] 正在执行 DOM 与 DSM 空间对齐重投影...")
    dsm_aligned, _, dom_transform = align_dsm_to_dom(dsm_path, image_path)

    # 3. 算法提取冠幅线
    log.info("[tool.draw-dsm] 调用算法模块 estimate_canopy_contours 提取单木冠幅边界...")
    boundary = estimate_canopy_contours(dsm_aligned, dom_transform)

    # 4. 载入原始 DOM 的 RGB 彩色图像以做图叠加底色
    dom_img = Image.open(img_path).convert("RGB")
    orig_w, orig_h = dom_img.size

    # 5. 自适应防 OOM 缩放
    max_draw_sz = 4096
    if max(orig_w, orig_h) > max_draw_sz:
        draw_scale = max_draw_sz / max(orig_w, orig_h)
        draw_w = int(round(orig_w * draw_scale))
        draw_h = int(round(orig_h * draw_scale))
        dom_img_resized = dom_img.resize((draw_w, draw_h), resample=Image.BILINEAR)
        
        # 相应地对 boundary 矩阵采用 Nearest 缩放以保持二值化精度
        boundary_im = Image.fromarray(boundary.astype(np.uint8) * 255)
        boundary_resized = boundary_im.resize((draw_w, draw_h), resample=Image.NEAREST)
        boundary_mask = np.array(boundary_resized) > 0
        dom_draw = np.array(dom_img_resized)
        log.info("[tool.draw-dsm] 原始图像尺寸过大 ({}x{})，等比例缩放至最大边 {}px 绘制。", orig_w, orig_h, max_draw_sz)
    else:
        boundary_mask = boundary
        dom_draw = np.array(dom_img)

    # 6. 进行半透明青色 (RGB: 0, 240, 255) 轮廓叠加
    alpha = 0.6  # 轮廓线不透明度
    cyan_color = np.array([0, 240, 255], dtype=np.float32)
    
    if np.any(boundary_mask):
        pixel_vals = dom_draw[boundary_mask].astype(np.float32)
        blended = pixel_vals * (1.0 - alpha) + cyan_color * alpha
        dom_draw[boundary_mask] = blended.astype(np.uint8)

    # 7. 保存结果
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    cache_dir = paths.subdir("tmp") / "draw_boxes"
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    out_path = cache_dir / f"{timestamp}_{img_path.stem}_dsm_crowns.jpg"

    Image.fromarray(dom_draw).save(out_path, quality=95)
    
    log.info("[tool.draw-dsm] DSM 冠幅边缘叠加渲染图保存成功: {}", out_path)
    print(f"Success: {out_path}")
    return 0
