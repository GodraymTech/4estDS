import os
import random
import numpy as np
import rasterio
from rasterio.windows import Window, transform as w_transform

def check_overlap(win1, win2):
    """检查两个 rasterio.windows.Window 是否重叠"""
    x1, y1, w1, h1 = win1.col_off, win1.row_off, win1.width, win1.height
    x2, y2, w2, h2 = win2.col_off, win2.row_off, win2.width, win2.height
    return not (x1 + w1 <= x2 or x2 + w2 <= x1 or y1 + h1 <= y2 or y2 + h2 <= y1)

def has_nodata(src, window, nodata_val):
    """检查窗口内是否含有 nodata 数据"""
    # 仅读取第一波段进行判断，加快检测速度
    data = src.read(1, window=window)
    
    if nodata_val is not None:
        if np.isnan(nodata_val):
            return np.isnan(data).any()
        else:
            return (data == nodata_val).any()
    else:
        # 如果未定义 nodata，以 0 值占比超过 0.1% 作为包含 nodata 的依据
        zero_ratio = np.mean(data == 0)
        return zero_ratio > 0.001

def random_crop(input_path, output_dir, num_crops=3, size=5000):
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"正在读取源图像: {input_path}")
    with rasterio.open(input_path) as src:
        width = src.width
        height = src.height
        nodata_val = src.nodata
        print(f"图像尺寸: {width}x{height}, 波段数: {src.count}, Nodata值: {nodata_val}")
        
        if width < size or height < size:
            raise ValueError(f"图像尺寸 ({width}x{height}) 小于裁剪大小 ({size}x{size})")
        
        selected_windows = []
        max_attempts = 5000
        attempts = 0
        
        while len(selected_windows) < num_crops and attempts < max_attempts:
            attempts += 1
            col_off = random.randint(0, width - size)
            row_off = random.randint(0, height - size)
            
            temp_window = Window(col_off, row_off, size, size)
            
            # 1. 检查是否与已选窗口重叠
            overlap = False
            for win in selected_windows:
                if check_overlap(temp_window, win):
                    overlap = True
                    break
            
            if overlap:
                continue
                
            # 2. 检查是否包含 nodata 区域
            if has_nodata(src, temp_window, nodata_val):
                continue
                
            selected_windows.append(temp_window)
            print(f"成功找到第 {len(selected_windows)} 个有效窗口: col_off={col_off}, row_off={row_off}")
            
        if len(selected_windows) < num_crops:
            raise RuntimeError(f"在尝试了 {max_attempts} 次后，仅找到 {len(selected_windows)} 个满足条件的窗口，无法满足数量要求。")
        
        # 开始裁剪并保存
        for idx, window in enumerate(selected_windows, 1):
            output_path = os.path.join(output_dir, f"zhanjiang_5000_{idx}.tif")
            print(f"\n正在写入第 {idx} 个窗口到 {output_path}...")
            
            new_transform = w_transform(window, src.transform)
            meta = src.meta.copy()
            meta.update({
                'height': size,
                'width': size,
                'transform': new_transform
            })
            
            with rasterio.open(output_path, 'w', **meta) as dst:
                for i in range(1, src.count + 1):
                    data = src.read(i, window=window)
                    dst.write(data, i)
                    print(f"  已写入第 {i} 波段")
            print(f"第 {idx} 个窗口保存成功！")

if __name__ == "__main__":
    input_tif = "/mnt/e/百度网盘下载/湛江红树林/Q16/result.tif"
    output_dir = "data/examples/zhanjiang_5000px"
    random_crop(input_tif, output_dir, num_crops=3, size=5000)
