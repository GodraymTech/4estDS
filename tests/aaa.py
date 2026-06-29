import os
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from PIL import Image

# Configure matplotlib for Chinese font support and Unicode minus sign on Mac/Linux/Windows
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'Heiti TC', 'PingFang SC', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

def get_stats(data):
    """Calculate common statistics for a given array of data."""
    if len(data) == 0:
        return {}
    return {
        "count": len(data),
        "min": float(np.min(data)),
        "max": float(np.max(data)),
        "mean": float(np.mean(data)),
        "median": float(np.median(data)),
        "std": float(np.std(data)),
        "p25": float(np.percentile(data, 25)),
        "p50": float(np.percentile(data, 50)),
        "p75": float(np.percentile(data, 75)),
        "p90": float(np.percentile(data, 90)),
        "p95": float(np.percentile(data, 95)),
        "p99": float(np.percentile(data, 99))
    }

def main():
    # Define directories
    workspace_dir = Path("/Users/aray/Downloads/待标注")
    dataset_dir = workspace_dir / "疑难_湛江麻章_极小幼林且水深"
    labels_dir = dataset_dir / "labels"
    images_dir = dataset_dir / "images"
    
    # Artifact output directory to save figures
    artifact_dir = Path("/Users/aray/.gemini/antigravity/brain/b9093525-e421-4910-8b52-7247701961b6")
    artifact_dir.mkdir(parents=True, exist_ok=True)

    widths_px = []
    heights_px = []
    areas_px = []
    ratios = []

    # Iterate over YOLO label files
    txt_files = list(labels_dir.glob("*.txt"))
    if not txt_files:
        print("No YOLO label files (.txt) found.")
        return

    print(f"Reading {len(txt_files)} label files...")
    for label_path in txt_files:
        # Exclude classes.txt which defines YOLO class names
        if label_path.name == "classes.txt":
            continue
            
        # Find corresponding image to get resolution
        # YOLO labels files usually share the same name as the image (e.g. .jpg, .png, .jpeg)
        img_path = None
        for ext in [".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"]:
            possible_path = images_dir / f"{label_path.stem}{ext}"
            if possible_path.exists():
                img_path = possible_path
                break
        
        if not img_path:
            print(f"Warning: Corresponding image for {label_path.name} not found in images directory. Skipping.")
            continue

        try:
            with Image.open(img_path) as img:
                W, H = img.size
        except Exception as e:
            print(f"Error opening image {img_path.name}: {e}. Skipping.")
            continue

        # Parse YOLO label file line by line
        try:
            with open(label_path, "r") as f:
                lines = f.readlines()
                for line in lines:
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        # YOLO format: class_id x_center y_center width height
                        w_rel = float(parts[3])
                        h_rel = float(parts[4])
                        
                        # Convert to absolute pixel dimensions
                        w_abs = w_rel * W
                        h_abs = h_rel * H
                        
                        widths_px.append(w_abs)
                        heights_px.append(h_abs)
                        areas_px.append(w_abs * h_abs)
                        ratios.append(w_abs / h_abs)
        except Exception as e:
            print(f"Error reading label file {label_path.name}: {e}")

    # Convert to numpy arrays for calculation
    widths = np.array(widths_px)
    heights = np.array(heights_px)
    areas = np.array(areas_px)
    aspect_ratios = np.array(ratios)
    side_lengths = np.sqrt(areas)  # Equivalent side length (pixels)

    total_bboxes = len(widths)
    print(f"Successfully processed {total_bboxes} bboxes.")
    
    if total_bboxes == 0:
        print("No bboxes found.")
        return

    # Calculate statistics
    w_stats = get_stats(widths)
    h_stats = get_stats(heights)
    ratio_stats = get_stats(aspect_ratios)
    area_stats = get_stats(areas)
    side_stats = get_stats(side_lengths)

    # Print statistical table to console
    print("\n--- BBOX STATISTICS TABLE ---")
    headers = ["Metric", "Width (px)", "Height (px)", "Aspect Ratio (W/H)", "Equivalent Side (px)", "Area (px^2)"]
    metrics = ["count", "min", "max", "mean", "median", "std", "p25", "p50", "p75", "p90", "p95", "p99"]
    print(f"{headers[0]:<20} | {headers[1]:<12} | {headers[2]:<12} | {headers[3]:<18} | {headers[4]:<20} | {headers[5]:<15}")
    print("-" * 105)
    for m in metrics:
        print(f"{m:<20} | {w_stats[m]:<12.2f} | {h_stats[m]:<12.2f} | {ratio_stats[m]:<18.4f} | {side_stats[m]:<20.2f} | {area_stats[m]:<15.1f}")

    # Write markdown statistics to a results file in artifact dir
    results_md_path = artifact_dir / "bbox_stats.md"
    with open(results_md_path, "w") as f_out:
        f_out.write("# 边界框 (BBox) 尺寸数据特征统计报告\n\n")
        f_out.write(f"本次共分析了 `疑难_湛江麻章_极小幼林且水深` 数据集中的 **{total_bboxes}** 个边界框。\n\n")
        f_out.write("### 常用统计值汇总表\n\n")
        f_out.write("| 统计指标 (Metrics) | 宽度 (Width, px) | 高度 (Height, px) | 宽高比 (Aspect Ratio, W/H) | 等效边长 (Equivalent Side, px) | 面积 (Area, px²) |\n")
        f_out.write("| :--- | :--- | :--- | :--- | :--- | :--- |\n")
        for m in metrics:
            f_out.write(f"| **{m}** | {w_stats[m]:.2f} | {h_stats[m]:.2f} | {ratio_stats[m]:.4f} | {side_stats[m]:.2f} | {area_stats[m]:.1f} |\n")

    # Generate and save separate plots
    style_color_w = '#1f77b4'
    style_color_h = '#ff7f0e'
    style_grid = True

    # Plot 1: Cumulative Distribution Function (CDF)
    plt.figure(figsize=(8, 6), dpi=150)
    sorted_w = np.sort(widths)
    sorted_h = np.sort(heights)
    y_vals = np.arange(1, len(sorted_w) + 1) / len(sorted_w)
    
    plt.plot(sorted_w, y_vals, label="宽度 (Width)", color=style_color_w, linewidth=2)
    plt.plot(sorted_h, y_vals, label="高度 (Height)", color=style_color_h, linewidth=2)
    plt.title("边界框 (BBox) 尺寸累积分布曲线 (CDF)", fontsize=14, fontweight='bold', pad=15)
    plt.xlabel("像素尺寸 (Pixels)", fontsize=12, labelpad=10)
    plt.ylabel("累积比例 (Cumulative Probability)", fontsize=12, labelpad=10)
    plt.grid(style_grid, linestyle='--', alpha=0.5)
    plt.legend(fontsize=11, loc="lower right")
    plt.xlim(0, max(np.max(widths), np.max(heights)) * 1.05)
    plt.ylim(0, 1.05)
    plt.tight_layout()
    plt.savefig(artifact_dir / "bbox_cdf.png", bbox_inches='tight')
    plt.close()

    # Plot 2: Width vs Height Scatter plot
    plt.figure(figsize=(8, 6), dpi=150)
    plt.scatter(widths, heights, alpha=0.6, color='#2ca02c', edgecolors='none', s=25, label="样本点 (BBoxes)")
    # Draw reference line W=H (1:1)
    max_val = max(np.max(widths), np.max(heights))
    plt.plot([0, max_val], [0, max_val], 'k--', alpha=0.5, label="1:1 参考线")
    plt.plot([0, max_val], [0, max_val * 2], 'r:', alpha=0.5, label="1:2 参考线")
    plt.plot([0, max_val * 2], [0, max_val], 'b:', alpha=0.5, label="2:1 参考线")
    
    plt.title("边界框宽高尺寸散点分布图 (Width vs Height)", fontsize=14, fontweight='bold', pad=15)
    plt.xlabel("宽度 (Width, px)", fontsize=12, labelpad=10)
    plt.ylabel("高度 (Height, px)", fontsize=12, labelpad=10)
    plt.grid(style_grid, linestyle='--', alpha=0.5)
    plt.legend(fontsize=11, loc="upper left")
    plt.xlim(0, np.max(widths) * 1.05)
    plt.ylim(0, np.max(heights) * 1.05)
    plt.gca().set_aspect('equal', adjustable='box')
    plt.tight_layout()
    plt.savefig(artifact_dir / "bbox_scatter.png", bbox_inches='tight')
    plt.close()

    # Plot 3: Aspect Ratio distribution histogram
    plt.figure(figsize=(8, 6), dpi=150)
    plt.hist(aspect_ratios, bins=50, color='#d62728', edgecolor='black', alpha=0.7)
    plt.axvline(1.0, color='k', linestyle='--', linewidth=1.5, label="宽高比 1.0 (正方形)")
    plt.title("边界框宽高比分布直方图 (Aspect Ratio)", fontsize=14, fontweight='bold', pad=15)
    plt.xlabel("宽高比 (Width / Height)", fontsize=12, labelpad=10)
    plt.ylabel("边界框频数 (Frequency)", fontsize=12, labelpad=10)
    plt.grid(style_grid, linestyle='--', alpha=0.5)
    plt.legend(fontsize=11)
    plt.tight_layout()
    plt.savefig(artifact_dir / "bbox_aspect_ratio.png", bbox_inches='tight')
    plt.close()

    # Plot 4: BBox Area distribution histogram (based on equivalent side length)
    plt.figure(figsize=(8, 6), dpi=150)
    plt.hist(side_lengths, bins=50, color='#9467bd', edgecolor='black', alpha=0.7)
    plt.title("边界框等效边长分布直方图 (Equivalent Side Length)", fontsize=14, fontweight='bold', pad=15)
    plt.xlabel("等效边长 $\sqrt{W \\times H}$ (Pixels)", fontsize=12, labelpad=10)
    plt.ylabel("边界框频数 (Frequency)", fontsize=12, labelpad=10)
    plt.grid(style_grid, linestyle='--', alpha=0.5)
    plt.tight_layout()
    plt.savefig(artifact_dir / "bbox_area.png", bbox_inches='tight')
    plt.close()

    print("Analysis complete! Statistics markdown and 4 plots saved successfully in the artifact directory.")

if __name__ == "__main__":
    main()
