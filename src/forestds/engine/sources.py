"""影像源:从真实栓格按读窗取像素(阶段三)。

优先 rasterio:支持超大 GeoTIFF 的窗口读(不整图载入内存),并携带地理变换。
缺失时回退 Pillow(整图载入,仅适中小影像,会告警)。
读出的窗口像素统一为 RGB (H, W, 3)。
"""
from __future__ import annotations

from loguru import logger as log


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
