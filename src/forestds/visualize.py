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
) -> bool:
    """在指定图像(支持文件路径或 PIL Image 实例)上绘制边界框并保存。

    Args:
        image: 输入图像路径或 PIL.Image.Image 实例。
        detections: 预测框列表，每个检测框需要有 x1, y1, x2, y2 属性或支持索引/字典访问。
        output_path: 保存路径，若为 None 且 image 为路径则覆盖原图，若 image 为 Image.Image 则必须提供。
        outline_color: 边界框颜色，默认红色。
        width: 边界框线宽。
        save_quality: 保存的图片质量。
    """
    if Image is None or ImageDraw is None:
        logger.warning("缺少 PIL 库，无法绘制检测框。")
        return False

    try:
        if isinstance(image, (str, Path)):
            im = Image.open(image)
            should_close = True
        elif hasattr(image, "convert"):  # PIL Image
            im = image
            should_close = False
        else:
            logger.error(f"不支持的图像输入类型: {type(image)}")
            return False

        draw_im = im.convert("RGB")
        draw = ImageDraw.Draw(draw_im)
        for d in detections:
            if hasattr(d, "x1") and hasattr(d, "y1") and hasattr(d, "x2") and hasattr(d, "y2"):
                bx1, by1, bx2, by2 = d.x1, d.y1, d.x2, d.y2
            elif isinstance(d, dict) and all(k in d for k in ("x1", "y1", "x2", "y2")):
                bx1, by1, bx2, by2 = d["x1"], d["y1"], d["x2"], d["y2"]
            elif (isinstance(d, tuple) or isinstance(d, list)) and len(d) >= 4:
                bx1, by1, bx2, by2 = d[0], d[1], d[2], d[3]
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
