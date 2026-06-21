"""公共可视化与绘图引擎。"""
from __future__ import annotations
from pathlib import Path
from loguru import logger

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None
    ImageDraw = None


def draw_detections_on_image(
    image: str | Path | Image.Image,
    detections: list,
    output_path: str | Path | None = None,
    outline_color: str = "red",
    width: int = 2,
    save_quality: int = 95,
    max_draw_size: int | None = 5000,
) -> bool:
    """在指定图像上绘制边界框并保存。对超大图支持中心裁剪绘制防 OOM 崩溃。

    Args:
        image: 输入图像路径或 PIL.Image.Image 实例。
        detections: 预测框列表，每个检测框需要有 x1, y1, x2, y2 属性。
        output_path: 保存路径。
        outline_color: 边界框颜色。
        width: 边界框线宽。
        save_quality: 保存的图片质量。
        max_draw_size: 触发中心裁剪的边长阈值（最小边长大于此值时启动）。
    """
    if Image is None or ImageDraw is None:
        logger.warning("缺少 PIL 库，无法绘制检测框。")
        return False

    try:
        x0, y0 = 0, 0
        im = None
        should_close = False

        if isinstance(image, (str, Path)):
            image_path = Path(image)
            # 1. 针对超大图的安全检测与高速窗口裁剪
            if max_draw_size is not None:
                W, H = 0, 0
                try:
                    import rasterio
                    with rasterio.open(image_path) as r_src:
                        W, H = r_src.width, r_src.height
                except Exception:
                    pass
                
                if W == 0 or H == 0:
                    with Image.open(image_path) as tmp_im:
                        W, H = tmp_im.size
                
                # 若最小边超过阈值，启动安全裁剪
                if min(W, H) > max_draw_size:
                    logger.info(f"【绘制检测框】: 原图尺寸 {min(W, H)}px > {max_draw_size}px，禁止整图绘制。自动切取中心 {max_draw_size}x{max_draw_size} 区域绘制。")
                    x0 = max(0, min(W - max_draw_size, W // 2 - max_draw_size // 2))
                    y0 = max(0, min(H - max_draw_size, H // 2 - max_draw_size // 2))
                    
                    try:
                        import rasterio
                        import numpy as np
                        with rasterio.open(image_path) as r_src:
                            window = rasterio.windows.Window(x0, y0, max_draw_size, max_draw_size)
                            rgb = []
                            for b_idx in (1, 2, 3):
                                if b_idx <= r_src.count:
                                    rgb.append(r_src.read(b_idx, window=window))
                                else:
                                    rgb.append(r_src.read(1, window=window))
                            rgb_arr = np.stack(rgb, axis=-1)
                            im = Image.fromarray(rgb_arr)
                    except Exception as e:
                        logger.warning(f"使用 rasterio 高速剪裁失败: {e}。退化到 PIL 裁剪（可能消耗较大内存）")
                        with Image.open(image_path) as full_im:
                            im = full_im.crop((x0, y0, x0 + max_draw_size, y0 + max_draw_size))
                    
                    should_close = True
            
            if im is None:
                im = Image.open(image_path)
                should_close = True
                
        elif hasattr(image, "convert"):  # PIL Image
            im = image
            should_close = False
        else:
            logger.error(f"不支持的图像输入类型: {type(image)}")
            return False

        draw_im = im.convert("RGB")
        draw = ImageDraw.Draw(draw_im)
        
        # 3. 绘制检测框（如果有做偏置，进行坐标平移与边界过滤）
        for d in detections:
            if hasattr(d, "x1") and hasattr(d, "y1") and hasattr(d, "x2") and hasattr(d, "y2"):
                bx1, by1, bx2, by2 = d.x1, d.y1, d.x2, d.y2
                if x0 > 0 or y0 > 0:
                    dcx, dcy = (d.center if hasattr(d, "center") else ((bx1 + bx2) / 2.0, (by1 + by2) / 2.0))
                    if not (x0 <= dcx < x0 + max_draw_size and y0 <= dcy < y0 + max_draw_size):
                        continue
                    bx1, by1, bx2, by2 = bx1 - x0, by1 - y0, bx2 - x0, by2 - y0
            elif isinstance(d, dict) and all(k in d for k in ("x1", "y1", "x2", "y2")):
                bx1, by1, bx2, by2 = d["x1"], d["y1"], d["x2"], d["y2"]
                if x0 > 0 or y0 > 0:
                    dcx = d.get("cx") or ((bx1 + bx2) / 2.0)
                    dcy = d.get("cy") or ((by1 + by2) / 2.0)
                    if not (x0 <= dcx < x0 + max_draw_size and y0 <= dcy < y0 + max_draw_size):
                        continue
                    bx1, by1, bx2, by2 = bx1 - x0, by1 - y0, bx2 - x0, by2 - y0
            elif (isinstance(d, tuple) or isinstance(d, list)) and len(d) >= 4:
                bx1, by1, bx2, by2 = d[0], d[1], d[2], d[3]
                if x0 > 0 or y0 > 0:
                    dcx = (bx1 + bx2) / 2.0
                    dcy = (by1 + by2) / 2.0
                    if not (x0 <= dcx < x0 + max_draw_size and y0 <= dcy < y0 + max_draw_size):
                        continue
                    bx1, by1, bx2, by2 = bx1 - x0, by1 - y0, bx2 - x0, by2 - y0
            else:
                continue
            draw.rectangle([bx1, by1, bx2, by2], outline=outline_color, width=width)

        if should_close:
            im.close()

        save_path = output_path
        if not save_path:
            if isinstance(image, (str, Path)):
                save_path = image
            else:
                logger.error("当传入 Image 实例时，必须提供 output_path")
                return False

        draw_im.save(save_path, "JPEG", quality=save_quality)
        return True
    except Exception as e:
        logger.error(f"绘制检测框到图像失败: {e}")
        return False
