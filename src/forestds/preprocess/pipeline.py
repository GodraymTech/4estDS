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
    slice_enable: bool | None = None,
    cog_enable: bool | None = None,
    cog_out: str | Path | None = None,
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
    4. 执行自标定 (SCOPE) 获取最佳 tile_size 和 overlap_rate
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
    do_cog = cog_enable if cog_enable is not None else settings.get("preprocess.cog.enable", True)
    do_slice = slice_enable if slice_enable is not None else settings.get("preprocess.slice.enable", True)
    resolved_slice_action = slice_action if slice_action is not None else settings.get("preprocess.slice.action", "slice")

    # 2. 测量宽高
    width, height = get_image_dimensions(image_path)

    # 3. 决定运行模式 (提前做，以判定是否是物理切片)
    has_large_size = (width > seed_window_size or height > seed_window_size)
    use_physical_slice = (do_slice and resolved_slice_action == "slice" and has_large_size)

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

    # 4. 检查 COG 状态并做必要的自动转换或路径重定向 (如果是物理切片，一律跳过 COG 的工作)
    is_cog = False
    if use_physical_slice:
        log.info("「静态切片」模式, 跳过 COG 影像格式检查与转换。")
    else:
        if is_tiff and do_cog:
            if max(width, height) < 5000:
                log.info("TIFF 影像尺寸 {}x{} 小于 5000 像素，自动跳过 COG 转换。", width, height)
                do_cog = False

        if is_tiff and do_cog:
            # 首先检测同目录下有无已转好的 _cog 文件，有则直接重定向过去
            if not path.stem.endswith("_cog"):
                cog_path = path.parent / f"{path.stem}_cog{path.suffix}"
                if cog_path.exists():
                    log.info(f"发现同级目录存在已转换 of COG 文件 {cog_path.name}，自动重定向影像路径。")
                    image_path = str(cog_path)
                    path = cog_path

            status = check_cog_format(image_path)
            if status == "cog":
                is_cog = True
            else:
                log.warning(f"影像 COG 状态检测结果为: {status}，需要转换。")
                if not cog_out:
                    out_suffix = settings.get("preprocess.cog.out_suffix", "_cog.tif") or "_cog.tif"
                    cog_out_path = path.parent / f"{path.stem}{out_suffix}"
                else:
                    cog_out_path = Path(cog_out)

                from .cog import convert_to_cog
                success = convert_to_cog(
                    image_path,
                    cog_out_path,
                    block_size=int(settings.get("preprocess.cog.block_size", 512)),
                    compress=str(settings.get("preprocess.cog.compress", "deflate")),
                    resampling=str(settings.get("preprocess.cog.resampling", "nearest")),
                    min_overview_dim=int(settings.get("preprocess.cog.min_overview_dim", 256))
                )
                if success:
                    log.info(f"COG 转换成功，后续步骤将使用转换后的 COG 影像: {cog_out_path}")
                    image_path = str(cog_out_path)
                    path = cog_out_path
                    is_cog = True
                else:
                    log.error("COG 转换失败，将基于原影像进行后续处理。")

            # 重新测量有可能因 COG 转换改变了路径的图像尺寸
            width, height = get_image_dimensions(image_path)
            has_large_size = (width > seed_window_size or height > seed_window_size)
            use_physical_slice = (do_slice and resolved_slice_action == "slice" and has_large_size)

    use_on_the_fly = (do_slice and not use_physical_slice and is_cog and has_large_size)

    if use_physical_slice:
        mode = "physical_slice"
    elif use_on_the_fly:
        mode = "on_the_fly"
    else:
        mode = "direct"

    # 5. 参数决策 (如果已经命中缓存，跳过自标定)
    if found_cache_dir:
        if resolved_tile_size is None:
            resolved_tile_size = int(settings.get("preprocess.slice.default_tile", 640))
        if resolved_overlap_rate is None:
            resolved_overlap_rate = float(settings.get("preprocess.slice.default_overlap", 0.2))
    else:
        # 只有在没有命中缓存时才决定是否跑自标定 (SCOPE)
        if mode in ("physical_slice", "on_the_fly"):
            if (resolved_tile_size is None or resolved_overlap_rate is None) and is_tiff and settings.get("preprocess.slice.scope.enable", True):
                log.info("触发 SCOPE: 自动寻优切割尺寸...")
                
                # 使用 scope 临时专用的 detector 实例，确保参数与 model_input 吻合
                from ..detect import get_detector
                arch_val = settings.get("arch", "yolo12")
                weights_val = settings.get(f"detect.models.{arch_val}.weights")
                conf_thr = float(settings.get("detect.conf_threshold", 0.25))
                iou_thr = float(settings.get("detect.iou_threshold", 0.6))
                
                scope_detector = get_detector(
                    arch_val,
                    weights=weights_val,
                    conf=conf_thr,
                    iou=iou_thr,
                    imgsz=int(settings.get("model_input", 1024)),
                    device=detector.kwargs.get("device") if detector else None,
                    verbose=settings.get("detect.verbose", True),
                )
                scope_tile, scope_overlap = run_scope_calibration(
                    image_path, scope_detector, settings, run_id=run_id
                )
                if resolved_tile_size is None:
                    resolved_tile_size = scope_tile
                if resolved_overlap_rate is None:
                    resolved_overlap_rate = scope_overlap
                log.debug("SCOPE 自标定决策：tile_size={}px, overlap_rate={:.0%}", resolved_tile_size, resolved_overlap_rate)

        if resolved_tile_size is None:
            resolved_tile_size = int(settings.get("preprocess.slice.default_tile", 640))
        if resolved_overlap_rate is None:
            resolved_overlap_rate = float(settings.get("preprocess.slice.default_overlap", 0.2))

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
                save_quality=int(settings.get("preprocess.slice.save_quality", 95))
            )
            if saved_count == 0:
                log.error("静态切片落盘失败，无可用瓦片")
                raise RuntimeError("slicing produced 0 tiles")
            
            # 必须是'tiles__{path.stem}'的形式，应对批量大图的场景
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
