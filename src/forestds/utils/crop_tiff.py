import os
import rasterio
from rasterio.windows import Window, transform as w_transform

input_path = 'data/xuwen_big.tif'
output_path = 'data/xuwen_center_5000.tif'

print(f"正在读取 {input_path}...")
with rasterio.open(input_path) as src:
    # 获取图像属性
    width = src.width
    height = src.height
    
    # 目标大小
    target_w, target_h = 5000, 5000
    
    # 计算中心偏移量
    col_off = (width - target_w) // 2
    row_off = (height - target_h) // 2
    
    print(f"原图尺寸: {width}x{height}")
    print(f"裁剪窗口偏移量: col_off={col_off}, row_off={row_off}, width={target_w}, height={target_h}")
    
    # 定义窗口
    window = Window(col_off, row_off, target_w, target_h)
    
    # 计算裁剪后的新地理变换矩阵
    new_transform = w_transform(window, src.transform)
    
    # 复制并更新元数据
    meta = src.meta.copy()
    meta.update({
        'height': target_h,
        'width': target_w,
        'transform': new_transform
    })
    
    # 读取窗口数据并写入新文件
    print(f"正在将裁剪后的图像写入 {output_path}...")
    with rasterio.open(output_path, 'w', **meta) as dst:
        # 分波段读取和写入，以节省内存并确保安全
        for i in range(1, src.count + 1):
            data = src.read(i, window=window)
            dst.write(data, i)
            print(f"已写入第 {i} 波段")
            
print("裁剪完成！")
