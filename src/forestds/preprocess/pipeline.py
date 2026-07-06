"""预处理业务流管道 (Pre-inference preparation)."""
from __future__ import annotations

from pathlib import Path
from loguru import logger as log

from ..utils import get_image_dimensions
from .. import paths
from .cog import check_cog_format
from .scope import run_scope_calibration
from .tiling import execute_slicing


def prepare_inference_image(
    image_path: str,
    *,
    slice_action: str | None = None,
    seed_window_size: int = 2560,
    tile_size: int | None = None,
    overlap_rate: float | None = None,
    settings = None,
    run_id: str = "preprocess",
    detector = None,
    out_dir: str | Path | None = None,
) -> dict:
    """对影像进行推理前的所有预处理准备逻辑，包括：
    1. 检查 COG 状态，支持同级 _cog 自动重定向与 COG 自动转换
    2. 读尺寸测量
    3. 判定路由模式 (physical_slice / on_the_fly / direct)
    4. 执行自标定 (SCOPE) 获取最佳 tile_size 和 overlap_rate (支持用户指定参数的显式短路)
    5. 如果满足静态切片条件，执行切片文件落盘
    
    返回包含了所有前置准备元数据及临时物理切片目录路径的字典：
    {
        "mode": "physical_slice" | "on_the_fly" | "direct",
        "width": int,
        "height": int,
        "is_tiff": bool,
        "is_cog": bool,
        "tile_size": int,
        "overlap_rate": float,
        "tiles_dir": Path | None,
        "saved_count": int,
        "image_path": str
    }
    """
    if settings is None:
        from ..config import load_settings
        settings = load_settings()

    path = Path(image_path)
    is_tiff = path.suffix.lower() in (".tif", ".tiff")

    # 1. 解析参数配置
    resolved_slice_action = slice_action if slice_action is not None else settings.get("preprocess.action", "dynamic")
    if resolved_slice_action not in ("static", "dynamic"):
        raise ValueError(f"不支持的预处理动作: {resolved_slice_action}。可选: dynamic, static")

    # 2. 测量宽高
    width, height = get_image_dimensions(image_path)
    has_large_size = (width > seed_window_size or height > seed_window_size)

    # 3. 对 TIFF 的 Tiled/COG 检测与自适应自动转换
    is_tiled_or_cog = False
    is_cog = False

    if is_tiff and has_large_size:
        # 首先检测同目录下有无已转好的 _cog 文件，有则直接重定向过去
        if not path.stem.endswith("_cog"):
            cog_path = path.parent / f"{path.stem}_cog{path.suffix}"
            if cog_path.exists():
                log.info(f"发现同级目录存在同名 COG 文件 {cog_path.name}，自动重定向影像路径。")
                image_path = str(cog_path)
                path = cog_path
                # 重新测量
                width, height = get_image_dimensions(image_path)
                has_large_size = (width > seed_window_size or height > seed_window_size)

        status = check_cog_format(image_path)
        if status in ("cog", "tiled_tiff"):
            log.info(f"TIFF 影像已为分块结构 (status: {status})，跳过 COG 格式转换。")
            is_tiled_or_cog = True
            is_cog = (status == "cog")
        elif status == "normal_tiff":
            # 对普通非分块 TIFF 且在 dynamic (动态滑窗) 模式下，强制自动转为 COG 以确保 I/O 随机读性能
            if resolved_slice_action == "dynamic":
                log.info(f"影像 {path.name} 属于普通非分块 TIFF，在动态模式下必须自动执行 COG 转换。")
                cog_out_path = path.parent / f"{path.stem}_cog.tif"

                from .cog import convert_to_cog
                # 将 COG 转换参数（如分块尺寸、压缩、重采样）在代码层固化为默认常量
                success = convert_to_cog(
                    image_path,
                    cog_out_path,
                    block_size=512,
                    compress="deflate",
                    resampling="nearest",
                    min_overview_dim=256
                )
                if success:
                    log.info(f"自动 COG 转换成功，后续步骤将使用转换后的 COG 影像: {cog_out_path}")
                    image_path = str(cog_out_path)
                    path = cog_out_path
                    is_tiled_or_cog = True
                    is_cog = True
                    # 重新测量
                    width, height = get_image_dimensions(image_path)
                    has_large_size = (width > seed_window_size or height > seed_window_size)
                else:
                    log.error("自动 COG 转换失败，后续将降级为原影像处理，并且由于缺失分块随机读支持将不得不强制走静态切片。")
                    is_tiled_or_cog = False
            else:
                log.info(f"影像 {path.name} 为普通非分块 TIFF，但处于静态模式跳过 COG 转换。")
                is_tiled_or_cog = False

    # 4. 根据分块特征做动/静切片路由决策
    use_tiled_read = (is_tiff and is_tiled_or_cog)
    use_physical_slice = False
    use_on_the_fly = False

    if has_large_size:
        if resolved_slice_action == "static" or not use_tiled_read:
            use_physical_slice = True
        else:
            use_on_the_fly = True

    if use_physical_slice:
        mode = "physical_slice"
    elif use_on_the_fly:
        mode = "on_the_fly"
    else:
        mode = "direct"

    # 【查 DB 切片缓存】
    found_cache_dir: Path | None = None
    resolved_tile_size = tile_size
    resolved_overlap_rate = overlap_rate

    if use_physical_slice:
        try:
            from ..db import reader
            db_url = settings.get("url", None)
            found_cache_dir = reader.find_cached_tiles(image_path, url=db_url)
        except Exception as db_err:
            log.warning("检索切片缓存失败: {}", db_err)

    # 5. 执行自标定 (SCOPE) 获取最佳 tile_size 和 overlap_rate (支持用户指定参数的显式短路)
    if mode in ("physical_slice", "on_the_fly"):
        # 显式短路：只要用户显式指定了 tile_size，直接跳过自标定寻优，以用户指定为准
        if resolved_tile_size is None and is_tiff and settings.get("preprocess.scope.enable", False):
            log.info("触发 SCOPE: 自动寻优切割尺寸...")
            
            # 如果传入了检测器，直接复用以节约内存和显存
            if detector is not None:
                scope_detector = detector
            else:
                from ..detect import get_detector
                arch_val = settings.get("detect.arch", "ultralytics")
                weights_val = settings.get(f"detect.models.{arch_val}.weights", settings.get("detect.weights"))
                conf_thr = float(settings.get("detect.conf_threshold", 0.25))
                iou_thr = float(settings.get("detect.iou_threshold", 0.6))
                
                scope_detector = get_detector(
                    arch_val,
                    weights=weights_val,
                    conf=conf_thr,
                    iou=iou_thr,
                    imgsz=int(settings.get("detect.model_input", settings.get("model_input", 1024))),
                    device=settings.get("detect.device", settings.get("device", None)),
                    verbose=settings.get("detect.verbose", True),
                )
            scope_tile, scope_overlap = run_scope_calibration(
                image_path, scope_detector, settings, run_id=run_id
            )
            resolved_tile_size = scope_tile
            resolved_overlap_rate = scope_overlap
            log.debug("SCOPE 自标定决策：tile_size={}px, overlap_rate={:.0%}", resolved_tile_size, resolved_overlap_rate)

    # 兜底默认值：若自标定未运行或未指定，则采用默认配置
    if resolved_tile_size is None:
        resolved_tile_size = int(settings.get("preprocess.default_tile_size", 1024))
    if resolved_overlap_rate is None:
        resolved_overlap_rate = float(settings.get("preprocess.default_overlap_rate", 0.1))

    # 6. 如果是静态切片，则执行落盘
    tiles_dir = None
    saved_count = 0
    if mode == "physical_slice":
        if found_cache_dir:
            tiles_dir = found_cache_dir
            saved_count = len(list(found_cache_dir.glob("*.*")))
        else:
            log.info("预处理模式: 「静态切片」. 执行落盘...")
            base_out = Path(out_dir) if out_dir is not None else paths.outputs_preprocess_dir()
            
            saved_count = execute_slicing(
                image_path=image_path,
                out_dir=base_out,
                tile_size=resolved_tile_size,
                overlap_rate=resolved_overlap_rate,
                run_id=run_id,
                save_quality=95 # JPEG 质量在代码层固化为默认常量 95
            )
            if saved_count == 0:
                log.error("静态切片落盘失败，无可用瓦片")
                raise RuntimeError("slicing produced 0 tiles")
            
            tiles_dir = base_out / f"tiles__{path.stem}"

            # 切片成功后立即把目录路径写入 DB，供下次缓存命中使用
            try:
                from ..db import writer as _writer
                _writer.update_tiles_dir(run_id, tiles_dir, url=settings.get("url", None))
            except Exception as e:
                log.warning("写入 tiles_dir 至 DB 失败（不影响推理）: {}", e)

    return {
        "mode": mode,
        "width": width,
        "height": height,
        "is_tiff": is_tiff,
        "is_cog": is_cog,
        "tile_size": resolved_tile_size,
        "overlap_rate": resolved_overlap_rate,
        "tiles_dir": tiles_dir,
        "saved_count": saved_count,
        "image_path": image_path,
    }
