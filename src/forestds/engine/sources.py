"""影像源:从真实栓格按读窗取像素(阶段三)。

优先 rasterio:支持超大 GeoTIFF 的窗口读(不整图载入内存),并携带地理变换。
缺失时回退 Pillow(整图载入,仅适中小影像,会告警)。
读出的窗口像素统一为 RGB (H, W, 3)。
"""
from __future__ import annotations

from loguru import logger as log
import numpy as np


class RasterImageSource:
    """从栓格文件按需读取窗口像素。

    属性: width / height / transform / crs(rasterio 路径才有几何信息)。
    方法: read_window(x, y, w, h) -> RGB (H, W, 3) 数组;空读窗返回 None。
    """

    def __init__(self, path: str, *, bands: tuple[int, ...] = (1, 2, 3)):
        self.path = path
        self.bands = bands
        self._ds = None          # rasterio dataset
        self._pil_array = None    # Pillow 回退的整图数组
        self.transform = None
        self.crs = None
        self._open()

    def _open(self) -> None:
        try:
            import rasterio
        except ImportError:
            rasterio = None
        if rasterio is not None:
            self._ds = rasterio.open(self.path)
            self.width = int(self._ds.width)
            self.height = int(self._ds.height)
            self.transform = self._ds.transform
            self.crs = self._ds.crs
            return
        # 回退 Pillow
        try:
            import numpy as np
            from PIL import Image
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "RasterImageSource 需要 rasterio 或 Pillow:  "
                "pip install '4estds[geo]'  或  pip install pillow"
            ) from e
        log.warning(
            "[raster] 未安装 rasterio,回退 Pillow 整图载入(仅适中小影像);"
            "超大 GeoTIFF 请安装 rasterio 以启用窗口读。"
        )
        img = Image.open(self.path).convert("RGB")
        self._pil_array = np.asarray(img)
        self.height, self.width = (int(v) for v in self._pil_array.shape[:2])

    def read_window(self, x: int, y: int, w: int, h: int):
        if w <= 0 or h <= 0:
            return None
        if self._ds is not None:
            import numpy as np
            from rasterio.windows import Window as RioWindow

            win = RioWindow(col_off=x, row_off=y, width=w, height=h)
            arr = self._ds.read(
                indexes=list(self.bands), window=win,
                boundless=True, fill_value=0,
            )
            # (bands, H, W) -> (H, W, bands)
            return np.transpose(arr, (1, 2, 0))
        # Pillow 回退:整图已在内存,直接切片
        return self._pil_array[y:y + h, x:x + w, :]

    def close(self) -> None:
        if self._ds is not None:
            self._ds.close()
            self._ds = None

    def __enter__(self) -> "RasterImageSource":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


from typing import Protocol, runtime_checkable

@runtime_checkable
class ImageSource(Protocol):
    """统一影像源接口协议。"""
    width: int
    height: int

    def read_window(self, x: int, y: int, w: int, h: int) -> np.ndarray | None:
        """从影像读取指定读窗像素，返回 (H, W, 3) 数组。"""
        ...

    def close(self) -> None:
        """关闭数据源，释放底层资源。"""
        ...


class InMemorySource:
    """包装内存中 RGB 像素数组的数据源。"""

    def __init__(self, array: np.ndarray):
        self._array = array
        self.height, self.width = array.shape[:2]

    def read_window(self, x: int, y: int, w: int, h: int) -> np.ndarray | None:
        if w <= 0 or h <= 0:
            return None
        return self._array[y:y + h, x:x + w, :]

    def close(self) -> None:
        pass

    def __enter__(self) -> InMemorySource:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


import re
from pathlib import Path
from PIL import Image

class TiledDirectorySource:
    """物理瓦片目录源。

    通过解析目录下形如 o{x}_{y}__s{tile_size}.jpg 的文件得到各瓦片的原始坐标，
    并将 read_window 请求路由到对应的瓦片文件读取。
    """

    def __init__(self, tiles_dir: str | Path, width: int, height: int):
        self.tiles_dir = Path(tiles_dir)
        self.width = width
        self.height = height
        self._tile_coords: list[tuple[int, int, int, int]] = []
        self._coord_to_file: dict[tuple[int, int, int, int], Path] = {}
        self._scan_tiles()

    def _scan_tiles(self) -> None:
        if not self.tiles_dir.exists():
            log.warning("物理瓦片目录不存在: {}", self.tiles_dir)
            return

        tile_files = sorted(list(self.tiles_dir.glob("*.jpg")))
        for f in tile_files:
            m = re.match(r"o(\d+)_(\d+)__s(\d+)", f.stem)
            if not m:
                continue
            wx, wy = int(m.group(1)), int(m.group(2))
            try:
                with Image.open(f) as img:
                    w_t, h_t = img.size
                coord = (wx, wy, w_t, h_t)
                self._tile_coords.append(coord)
                self._coord_to_file[coord] = f
            except Exception as e:
                log.warning("扫描解析物理瓦片 {} 失败: {}", f.name, e)

    def get_slice_windows(self) -> list[tuple[int, int, int, int]]:
        return self._tile_coords

    def read_window(self, x: int, y: int, w: int, h: int) -> np.ndarray | None:
        coord = (x, y, w, h)
        file_path = self._coord_to_file.get(coord)
        if not file_path:
            log.warning("未找到匹配坐标的物理瓦片: (x={}, y={}, w={}, h={})", x, y, w, h)
            return None
        try:
            with Image.open(file_path) as img:
                return np.asarray(img.convert("RGB"))
        except Exception as e:
            log.warning("读取物理瓦片像素失败: {}, 错误: {}", file_path, e)
            return None

    def close(self) -> None:
        pass

    def __enter__(self) -> TiledDirectorySource:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
