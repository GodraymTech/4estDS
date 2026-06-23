"""SCOPE (Self-Calibrating Optimal Patch-size Estimation) 自标定自适应切片。

核心机制：
1. 空间分层网格采样：在超大正射影像中选取少量 2560x2560 窗口。
2. 自相似四叉多尺度探针：每窗口切出 37 张子图（L0/L1/L2/L3），L3 剪枝。
3. 像素制缩放命名落盘：缩放到 640x640，文件名包含 {image_stem}__run_{run_id}__o{gx}_{gy}__s{T}.jpg。
4. 批量预推理与非完整树剔除：过滤边界剪裁目标。
5. 坐标回贴与跨尺度去重。
6. 召回反卷积去偏：消除检测器尺寸偏好，估算真实冠幅像素分布。
7. 联合目标博弈求解：权衡算力与边界截断，计算最优 T* 和 r*。
"""
from __future__ import annotations

import math
import os
import random
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from loguru import logger as log
from ..detect.base import Window

try:
    import numpy as np
    import rasterio
    from PIL import Image
except ImportError:
    np = None
    rasterio = None
    Image = None


@dataclass
class Detection:
    x1: float
    y1: float
    x2: float
    y2: float
    score: float
    label: str

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def center(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0


def compute_iou(box1: tuple[float, float, float, float], box2: tuple[float, float, float, float]) -> float:
    x1_max = max(box1[0], box2[0])
    y1_max = max(box1[1], box2[1])
    x2_min = min(box1[2], box2[2])
    y2_min = min(box1[3], box2[3])

    inter_width = max(0.0, x2_min - x1_max)
    inter_height = max(0.0, y2_min - y1_max)
    inter_area = inter_width * inter_height

    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union_area = area1 + area2 - inter_area

    if union_area <= 0:
        return 0.0
    return inter_area / union_area


def detector_recall_curve(a: float) -> float:
    """预先标定的检测器召回率与表观尺寸的关系曲线 R(a)。
    
    物理背景依据：尺度空间理论 (Lindeberg's Scale-Space) 与检测器尺度甜区效应。
    数学背景依据：基于对数尺度几何级数对称性的对数正态包络模型 (Log-Normal Envelope)。
    专利实施参考：该经验参数 (最佳甜区=80px, 对数带宽=0.8) 可由算法通过对标注样本
    进行合成尺度缩放并实测拟合自适应产生，以适配不同检测器架构 (如 YOLO vs RT-DETR)。
    """
    if a <= 0:
        return 0.05
    # 峰值在 80px 左右，方差在对数空间内约 0.8
    r = math.exp(-((math.log(a) - math.log(80.0)) ** 2) / (2 * (0.8 ** 2)))
    return max(0.05, r)  # 避免除以 0 导致数值发散


def weighted_quantile(sizes: list[float], weights: list[float], q: float) -> float:
    """计算加权分位数。"""
    if not sizes:
        return 0.0
    pairs = sorted(zip(sizes, weights), key=lambda x: x[0])
    sorted_sizes = [x[0] for x in pairs]
    sorted_weights = [x[1] for x in pairs]
    sum_w = sum(sorted_weights)
    if sum_w <= 0:
        return sorted_sizes[0]
    cum_w = 0.0
    for sz, w in zip(sorted_sizes, sorted_weights):
        cum_w += w
        if cum_w >= sum_w * q:
            return sz
    return sorted_sizes[-1]


def solve_joint_optimization(
    sizes_px: list[float],
    weights: list[float],
    width_full: int,
    height_full: int,
    lambda_cost: float = 0.15,
    large_quantile: float = 0.95,
    tile_grid: list[int] | None = None,
    overlap_ratios: list[float] | None = None,
    probe_size: int = 640,
) -> tuple[int, float]:
    """通过 Horvitz-Thompson 加权无偏估计求解联合最优化目标函数，计算最优切片尺寸 T* 与重叠率 r*。"""
    if not sizes_px:
        # 回退默认值
        return 1024, 0.2

    # 1. 采用加权分位数(Weighted Quantile)精准估算无偏大树冠物理尺寸 d_q95
    d_q95 = weighted_quantile(sizes_px, weights, large_quantile)
    sum_w = sum(weights)

    log.debug(f"经验冠幅尺寸无偏估计: 样本数={len(sizes_px)}, 加权总体={sum_w:.1f}, 95分位数(大冠幅)={int(round(d_q95))}px")

    area_full = width_full * height_full
    if tile_grid is None:
        tile_grid = [512, 640, 768, 896, 1024, 1280, 1536, 2048]
    if overlap_ratios is None:
        overlap_ratios = [0.1, 0.15, 0.2, 0.25, 0.3]

    best_T, best_r = 1024, 0.2
    best_J = -float("inf")

    for T in tile_grid:
        for r in overlap_ratios:
            # 物理约束: 重叠部分必须大于大冠幅尺度，防大树跨缝被截断
            if r * T < d_q95:
                continue

            # 2. 统计学连续加权边界截断与检测召回期望
            total_weighted_recall = 0.0
            for d, w in zip(sizes_px, weights):
                # 几何截断概率模型
                p_cut = (d - r * T) / (T * (1.0 - r))
                p_cut = max(0.0, min(1.0, p_cut))
                
                # 缩放后的表观尺寸 a
                a = float(probe_size) * d / T
                rec = detector_recall_curve(a)
                # 该样本的有效检出概率乘以其在大自然中的真实频数权重 w
                total_weighted_recall += w * rec * (1.0 - p_cut)
            
            mean_recall = total_weighted_recall / sum_w

            # 3. 算力开销：正比于切片数
            step = T * (1.0 - r)
            computational_cost = lambda_cost * (area_full / (step ** 2)) / 100.0  # 缩放平衡常数

            # 联合博弈决策函数
            J = mean_recall - computational_cost
            if J > best_J:
                best_J = J
                best_T = T
                best_r = r

    log.info(f"联合优化求解完成: 最优边长 T*={best_T}px, 最优重叠率 r*={best_r:.0%}")
    return best_T, best_r


def run_scope_calibration(
    image_path: str | Path,
    detector=None,
    settings=None,
    run_id: str = "scope",
) -> tuple[int, float]:
    """执行 SCOPE 自标定全流程。返回 (T_star, r_star)。"""
    if np is None or rasterio is None or Image is None:
        log.warning("缺失依赖 (numpy/rasterio/Pillow)，跳过自标定，回退默认值。")
        return 640, 0.2

    # 直接使用扁平化属性调用（settings.get 支持叶子节点唯一键扁平化检索）
    if settings is None:
        from ..config import Settings
        settings = Settings()

    if detector is None:
        raise ValueError("SCOPE self-calibration requires a valid detector instance. No detector was provided or initialization failed.")

    # 临时禁用自标定推理时的 verbose 输出，避免日志污染
    orig_verbose = detector.kwargs.get("verbose", True)
    detector.kwargs["verbose"] = False

    seed_window_size = int(settings.get("seed_window_size", 2560))
    probe_size = int(settings.get("detect.model_input", 640))

    sample_budget = int(settings.get("sample_budget", 16))
    sample_delta = int(settings.get("sample_delta", 4))
    nodata_tolerance = float(settings.get("nodata_tolerance", 0.05))
    
    iou_threshold = float(settings.get("preprocess.slice.scope.iou_threshold", 0.45))
    
    large_quantile = float(settings.get("large_quantile", 0.95))
    lambda_cost = float(settings.get("lambda_cost", 0.15))
    incomplete_area_ratio = float(settings.get("incomplete_area_ratio", 0.9))
    incomplete_border_px = int(settings.get("incomplete_border_px", 2))
    
    scope_batch_size = int(settings.get("batch_size", 16))
    save_quality = int(settings.get("save_quality", 95))
    draw_box = bool(settings.get("preprocess.slice.scope.draw_box", False))
    
    tile_grid = settings.get("tile_grid", [512, 640, 768, 896, 1024, 1280, 1536, 2048])
    overlap_grid = settings.get("overlap_grid", [0.1, 0.15, 0.2, 0.25, 0.3])

    path = Path(image_path)
    if not path.exists():
        log.error(f"输入影像不存在: {path}")
        return 640, 0.2

    from ..utils import get_image_dimensions
    W, H = get_image_dimensions(path)

    log.debug(f"开始对影像 {path.name}({W}x{H}) 进行 SCOPE 尺度空间探测...")

    # 创建临时工作区
    tmp_dir = Path(tempfile.mkdtemp(prefix="scope_tiling_"))
    
    # 尺度分布样本集与对应的反卷积召回权重
    detected_sizes: list[float] = []
    detected_weights: list[float] = []
    sampled_coords: list[tuple[int, int]] = []

    try:
        # 阶段 1: 分层网格种子窗口选择与序贯停止
        # 动态计算网格步长，等于种子窗口物理边长，以确保候选窗口尽可能不重叠
        step = seed_window_size
        grid_cols = min(max(1, W // step), 8)
        grid_rows = min(max(1, H // step), 8)

        # 在全图 grid_cols x grid_rows 网格中挑选
        # x/y_steps是网格线的`交叉点`，用来作为种子窗口的`中心点`，gx/gy则是种子窗口的`左上角`。
        x_steps = [int(W * i / (grid_cols + 1)) for i in range(1, grid_cols + 1)]
        y_steps = [int(H * i / (grid_rows + 1)) for i in range(1, grid_rows + 1)]
        log.info(f"种子窗口({seed_window_size}px) 均匀分布中心点数量: {len(x_steps)} x {len(y_steps)} = {len(x_steps) * len(y_steps)}")
        candidates = []
        seen_coords = set()
        for xs in x_steps:
            for ys in y_steps:
                # 保证窗口 seed_window_size x seed_window_size 不越界
                half_seed = seed_window_size // 2
                gx = min(max(0, W - seed_window_size), max(0, xs - half_seed))
                gy = min(max(0, H - seed_window_size), max(0, ys - half_seed))
                if (gx, gy) not in seen_coords:
                    seen_coords.add((gx, gy))
                    candidates.append((gx, gy))
        
        random.shuffle(candidates)

        # 动态根据有效候选窗口数量调整采样参数，防止越界或不足
        actual_sample_budget = min(sample_budget, len(candidates))
        actual_sample_delta = min(sample_delta, len(candidates))

        # 分轮采样
        win_idx = 0
        while win_idx < len(candidates) and len(sampled_coords) < actual_sample_budget:
            delta = min(actual_sample_delta, actual_sample_budget - len(sampled_coords))
            batch_candidates = candidates[win_idx:win_idx + delta]
            win_idx += delta

            new_crops = []
            with rasterio.open(path) as src:
                for gx, gy in batch_candidates:
                    # Nodata 占比过滤 (积分图或快速采样)
                    # 读窗并快速计算 0 占比。避免使用 rasterio 容易在 C 层引发 SegFault 的 out_shape 参数
                    samp_full = src.read(1, window=rasterio.windows.Window(gx, gy, seed_window_size, seed_window_size))
                    samp = samp_full[::40, ::40]
                    nodata_ratio = np.sum(samp == 0) / samp.size
                    if nodata_ratio > nodata_tolerance:
                        log.debug(f"窗口 ({gx}, {gy}) nodata 占比 {nodata_ratio:.0%} > {nodata_tolerance:.0%}，舍弃。")
                        continue

                    # 记录成功窗口
                    sampled_coords.append((gx, gy))

                    # 阶段 2: 自相似四叉多尺度探针 (L0 ~ L3)
                    sz0 = seed_window_size
                    sz1 = seed_window_size // 2
                    sz2 = seed_window_size // 4
                    sz3 = seed_window_size // 8

                    levels = {
                        0: [(0, 0, sz0)],
                        1: [(dx, dy, sz1) for dx in (0, sz1) for dy in (0, sz1)],
                        2: [(dx, dy, sz2) for dx in range(0, sz0, sz2) for dy in range(0, sz0, sz2)],
                    }
                    
                    # 生成 L3 (sz3) 并剪枝
                    l3_tiles = []
                    for dx in range(0, sz0, sz2):
                        for dy in range(0, sz0, sz2):
                            # 每个 sz2 节点下有 4 个 sz3 节点，随机挑 1 个
                            cx = dx + random.choice([0, sz3])
                            cy = dy + random.choice([0, sz3])
                            l3_tiles.append((cx, cy, sz3))
                    levels[3] = l3_tiles

                    # 静态切片落盘
                    for L, tiles in levels.items():
                        for tx, ty, T_size in tiles:
                            full_x = gx + tx
                            full_y = gy + ty
                            
                            # 裁切图像并缩放至 640x640 保存为 JPG
                            window = rasterio.windows.Window(full_x, full_y, T_size, T_size)
                            # 读取三通道
                            rgb = []
                            for b_idx in (1, 2, 3):
                                if b_idx <= src.count:
                                    rgb.append(src.read(b_idx, window=window))
                                else:
                                    # 单通道补齐
                                    rgb.append(src.read(1, window=window))
                            
                            rgb_arr = np.stack(rgb, axis=-1)
                            img = Image.fromarray(rgb_arr)
                            img_resized = img.resize((probe_size, probe_size), Image.Resampling.BILINEAR)

                            # 阶段 3: 像素制命名规范
                            # {image_stem}__run_{run_id}__o{gx}_{gy}__s{T}.jpg
                            tile_name = f"{path.stem}__run_{run_id}__o{full_x}_{full_y}__s{T_size}__resize{probe_size}.jpg"
                            img_path = tmp_dir / tile_name
                            img_resized.save(img_path, "JPEG", quality=save_quality)
                            new_crops.append((img_path, full_x, full_y, T_size))

            if not new_crops:
                continue

            # 阶段 4: 批量预推理
            batch_dets: list[tuple[Detection, int, int, int]] = []
            try:
                windows_to_infer = []
                for img_p, fx, fy, t_sz in new_crops:
                    # 重新读入 640x640 的 numpy pixels
                    with Image.open(img_p) as im:
                        arr = np.asarray(im)
                    # 与 detector.predict_batch 的参数 Window 对齐
                    win = Window(x=0, y=0, w=probe_size, h=probe_size, pixels=arr)
                    windows_to_infer.append((win, fx, fy, t_sz, img_p))
                
                # 执行分批预测，防 CUDA Out Of Memory (OOM)
                detector.ensure_loaded()
                res_list = []
                for idx in range(0, len(windows_to_infer), scope_batch_size):
                    sub_batch = windows_to_infer[idx:idx + scope_batch_size]
                    sub_res = detector.predict_batch([item[0] for item in sub_batch])
                    res_list.extend(sub_res)
                
                for (win, fx, fy, t_sz, img_p), detections in zip(windows_to_infer, res_list):
                    if draw_box:
                        try:
                            from .. import paths
                            # 重新裁剪原生 resize 前尺寸的切片图以保留高清细节与像素物理尺度
                            with rasterio.open(path) as r_src:
                                window = rasterio.windows.Window(fx, fy, t_sz, t_sz)
                                rgb = []
                                for b_idx in (1, 2, 3):
                                    if b_idx <= r_src.count:
                                        rgb.append(r_src.read(b_idx, window=window))
                                    else:
                                        rgb.append(r_src.read(1, window=window))
                                rgb_arr = np.stack(rgb, axis=-1)
                                raw_im = Image.fromarray(rgb_arr).convert("RGB")
                            
                            # 缩放因子：由 640 映射回原生 T_size
                            scale = float(t_sz) / float(probe_size)
                            scaled_dets = []
                            for d in detections.items:
                                scaled_dets.append({
                                    "x1": d.x1 * scale,
                                    "y1": d.y1 * scale,
                                    "x2": d.x2 * scale,
                                    "y2": d.y2 * scale,
                                })
                            
                            debug_dir = paths.outputs_preprocess_dir() / f"scopedebug__{path.stem}"
                            debug_dir.mkdir(parents=True, exist_ok=True)
                            raw_vis_out = debug_dir / f"o{fx}_{fy}__s{t_sz}_detected.jpg"
                            
                            from ..export.visualize import draw_detections_on_image
                            draw_detections_on_image(
                                raw_im,
                                scaled_dets,
                                output_path=raw_vis_out,
                                outline_color="red",
                                width=max(2, int(round(scale * 1.5))),
                                save_quality=save_quality,
                            )
                        except Exception as e:
                            log.warning(f"绘制原生自标定图像检测框失败: {e}")

                    for d in detections.items:
                        bx1, by1, bx2, by2 = d.x1, d.y1, d.x2, d.y2
                        w_box = bx2 - bx1
                        h_box = by2 - by1
                        
                        # 非完整树剔除
                        # 主判据: 面积占比 > incomplete_area_ratio，或与边框非常接近
                        if (w_box * h_box) / (probe_size * probe_size) > incomplete_area_ratio:
                            continue
                        if (
                            bx1 < incomplete_border_px
                            or by1 < incomplete_border_px
                            or bx2 > probe_size - incomplete_border_px
                            or by2 > probe_size - incomplete_border_px
                        ):
                            # 紧贴边缘，视为非完整树
                            continue
                            
                        det = Detection(bx1, by1, bx2, by2, d.score, d.label)
                        batch_dets.append((det, fx, fy, t_sz))
            except (FileNotFoundError, ImportError) as e:
                raise e
            except Exception as e:
                log.exception("预推理异常")
                raise e

            # 阶段 5: 坐标回贴与跨尺度去重
            # gx1, gy1, gx2, gy2 -> 全图像素坐标，并保留检测时的原生表观尺寸 det_w
            global_boxes: list[tuple[float, float, float, float, float, float, float]] = []
            for det, fx, fy, t_sz in batch_dets:
                scale = t_sz / float(probe_size)
                gx1 = fx + det.x1 * scale
                gy1 = fy + det.y1 * scale
                gx2 = fx + det.x2 * scale
                gy2 = fy + det.y2 * scale
                
                # 大图物理直径 d，以及模型上的表观探测尺寸 det_w (即局部坐标系下的最大边长)
                d = max(gx2 - gx1, gy2 - gy1)
                det_w = max(det.x2 - det.x1, det.y2 - det.y1)
                global_boxes.append((gx1, gy1, gx2, gy2, det.score, d, det_w))

            # 简单去重 (NMS-like)
            global_boxes.sort(key=lambda x: x[4], reverse=True)
            keep_boxes = []
            for box in global_boxes:
                overlap = False
                for kbox in keep_boxes:
                    if compute_iou(box[:4], kbox[:4]) > iou_threshold:
                        overlap = True
                        break
                if not overlap:
                    keep_boxes.append(box)

            # 阶段 6: 计算召回反卷积无偏统计权重
            for box in keep_boxes:
                d = box[5]
                det_w_actual = box[6]
                rec = detector_recall_curve(det_w_actual)
                
                detected_sizes.append(d)
                detected_weights.append(1.0 / rec)

            # 评估序贯停止条件
            if len(detected_sizes) > 10:
                # 采用加权分位数算法，在线评估大冠幅参考尺寸估计量 theta
                d_q95 = weighted_quantile(detected_sizes, detected_weights, large_quantile)
                sum_w = sum(detected_weights)

                # 采用加权自助重采样 (Weighted Bootstrap Resampling) 估算不确定性置信区间半宽
                theta_samples = []
                for _ in range(50):
                    # 有放回加权抽样
                    resample = random.choices(detected_sizes, weights=detected_weights, k=len(detected_sizes))
                    resample.sort()
                    theta_samples.append(resample[int(len(resample) * large_quantile)])
                
                theta_samples.sort()
                ci_half = (theta_samples[int(50 * 0.95)] - theta_samples[int(50 * 0.05)]) / 2.0
                
                log.debug(f"采样进度: 激活窗口={len(sampled_coords)}/{actual_sample_budget}, 样本数={len(detected_sizes)} (+{len(keep_boxes)}), 加权总体={sum_w:.1f}, 大冠幅估计d_q95={int(round(d_q95))}px, CI半宽={int(round(ci_half))}px")
                
                if ci_half < 2.0 and len(sampled_coords) >= actual_sample_delta * 2:
                    log.info(f"序贯检测收敛 (CI半宽 {int(round(ci_half))} < 2px)，提前结束探测。")
                    break

        log.info(f"🎇 SCOPE探测结束: 种子窗口 {len(sampled_coords)} 个, 有效bbox {len(detected_sizes)} 个。")

        # 阶段 7: 最优几何求解
        T_star, r_star = solve_joint_optimization(
            detected_sizes,
            detected_weights,
            W,
            H,
            lambda_cost=lambda_cost,
            large_quantile=large_quantile,
            tile_grid=tile_grid,
            overlap_ratios=overlap_grid,
            probe_size=probe_size,
        )
        return T_star, r_star

    finally:
        # 恢复 verbose 设置
        if detector is not None:
            detector.kwargs["verbose"] = orig_verbose
        # 清理临时文件
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
