"""地理仿射变换与真实面积解析（阶段六补全）。

目标：从影像获取仿射变换参数 -> 算出像元地面尺寸(GSD) -> 真实地块面积 -> 密度(株/公顷)。

三条获取路径，依可靠性/依赖克制原则依次尝试：
  1. rasterio dataset 的 transform/crs（若调用方已打开）——最权威。
  2. sidecar 世界文件 .tfw/.tifw/.wld（6 个纯文本浮点）+ 可选 .prj(WKT) 判定坐标系/单位。
  3. GeoTIFF 内嵌标签（ModelPixelScale 33550 / ModelTransformation 34264 / GeoKeyDirectory 34735），纯 Pillow 读取。
  均不可得时返回 None，上层保持“面积未知”的诚实降级。

设计上严格区分几何（仿射变换）与单位（坐标系）两个关心：
  - 投影坐标系(如 UTM)：像元尺寸本身就是米，面积 = |det(A)| * 线性单位²。
  - 地理坐标系(经纬度)：像元尺寸是度，需用纬度近似换算为米（并告警）。
"""
from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass

log = logging.getLogger("fourestds")

# 赤道附近每度纬度约 111320 m（WGS84 平均）。
_M_PER_DEG_LAT = 111320.0
# 常见 EPSG 线性单位码 -> 米。
_EPSG_LINEAR_UNIT_M = {9001: 1.0, 9002: 0.3048, 9003: 0.3048006096012192}
# 世界文件后缀（按优先级）。
_WORLD_SUFFIXES = (".tfw", ".tifw", ".wld", ".tiffw")


@dataclass(frozen=True)
class Affine:
    """仿射变换: x = a*col + b*row + c ; y = d*col + e*row + f。

    与 GDAL geotransform (c,a,b,f,d,e)、世界文件 (a,d,b,e,c,f) 可互转。
    """

    a: float
    b: float
    c: float
    d: float
    e: float
    f: float

    def pixel_area(self) -> float:
        """单像元占地面积（输入坐标单位的平方）= |det([[a,b],[d,e]])|。"""
        return abs(self.a * self.e - self.b * self.d)

    def pixel_size_x(self) -> float:
        return math.hypot(self.a, self.d)

    def pixel_size_y(self) -> float:
        return math.hypot(self.b, self.e)

    def pixel_to_world(self, col: float, row: float) -> tuple[float, float]:
        """像素坐标(col,row) -> 世界坐标(x,y)。"""
        x = self.a * col + self.b * row + self.c
        y = self.d * col + self.e * row + self.f
        return (x, y)

    def world_to_pixel(self, x: float, y: float) -> tuple[float, float]:
        """世界坐标(x,y) -> 像素坐标(col,row)，仿射逆变换。"""
        det = self.a * self.e - self.b * self.d
        if abs(det) < 1e-15:
            raise ValueError("仿射矩阵不可逆(det≈0)，无法反解像素坐标")
        dx = x - self.c
        dy = y - self.f
        col = (self.e * dx - self.b * dy) / det
        row = (-self.d * dx + self.a * dy) / det
        return (col, row)

    @classmethod
    def from_world_file(cls, lines) -> "Affine":
        """世界文件 6 行: A(x-scale), D, B, E(y-scale,通常负), C(上左像元**中心**x), F(y)。"""
        vals = [float(x) for x in lines if str(x).strip() != ""]
        if len(vals) < 6:
            raise ValueError(f"世界文件需 6 个数值,实得 {len(vals)}")
        A, D, B, E, C, F = vals[:6]
        return cls(a=A, b=B, c=C, d=D, e=E, f=F)

    @classmethod
    def from_gdal(cls, gt) -> "Affine":
        """GDAL geotransform: (c, a, b, f, d, e)。"""
        c, a, b, f, d, e = (float(v) for v in gt[:6])
        return cls(a=a, b=b, c=c, d=d, e=e, f=f)

    @classmethod
    def from_pixel_scale(cls, sx: float, sy: float, ox: float = 0.0, oy: float = 0.0) -> "Affine":
        """由 ModelPixelScale (sx, sy) 构造北上仿射(y 向下为负)。"""
        return cls(a=abs(sx), b=0.0, c=ox, d=0.0, e=-abs(sy), f=oy)

    @classmethod
    def from_rasterio(cls, transform) -> "Affine":
        """rasterio.Affine 属性 a,b,c,d,e,f 与本类一致。"""
        return cls(
            a=float(transform.a), b=float(transform.b), c=float(transform.c),
            d=float(transform.d), e=float(transform.e), f=float(transform.f),
        )


@dataclass(frozen=True)
class GeoInfo:
    """仿射变换 + 坐标系语义，由此推出真实米制面积与 GSD。"""

    transform: Affine
    crs_kind: str = "unknown"          # projected | geographic | unknown
    linear_unit_m: float = 1.0          # 投影坐标系的线性单位->米
    origin_lat: float | None = None     # 地理坐标系度->米所需纬度
    source: str = "unknown"             # rasterio | world_file | geotiff_tags

    def pixel_area_m2(self) -> float | None:
        """单像元真实地面面积(㎡)；无法可靠推算时返回 None。"""
        if self.crs_kind == "geographic":
            if self.origin_lat is None:
                log.warning("[geo] 地理坐标系但缺纬度,无法将度换算为米,面积置空。")
                return None
            dx_deg = abs(self.transform.a)  # 经度方向像元尺寸(度)
            dy_deg = abs(self.transform.e)  # 纬度方向像元尺寸(度)
            m_per_deg_lon = _M_PER_DEG_LAT * math.cos(math.radians(self.origin_lat))
            log.warning(
                "[geo] 地理坐标系,在纬度 %.4f° 处用近似换算度->米(结果为近似值)。",
                self.origin_lat,
            )
            return (dx_deg * m_per_deg_lon) * (dy_deg * _M_PER_DEG_LAT)
        # projected / unknown: 假定线性米制
        return self.transform.pixel_area() * (self.linear_unit_m ** 2)

    def gsd_m(self) -> float | None:
        """地面采样间隔(米/像元),取 x/y 像元尺寸几何均值。"""
        pa = self.pixel_area_m2()
        if pa is None or pa < 0:
            return None
        return math.sqrt(pa)


# --------------------------------------------------------------------------
# sidecar 解析
# --------------------------------------------------------------------------
def _find_sidecar(image_path: str, suffixes) -> str | None:
    base, _ = os.path.splitext(image_path)
    for suf in suffixes:
        cand = base + suf
        if os.path.isfile(cand):
            return cand
    return None


def _parse_prj(text: str) -> tuple[str, float]:
    """极简 WKT 扫描: 返回 (crs_kind, linear_unit_m)。不做完整 WKT 解析。"""
    up = text.upper()
    if "PROJCS" in up or "PROJCRS" in up:
        kind = "projected"
    elif "GEOGCS" in up or "GEOGCRS" in up:
        return "geographic", 1.0
    else:
        return "unknown", 1.0
    # 投影坐标系: 取最后一个 UNIT[...] 的换算因子作为线性单位。
    unit_m = 1.0
    idx = up.rfind("UNIT[")
    if idx >= 0:
        seg = text[idx + 5:]
        try:
            parts = seg.split(",")
            factor = float(parts[1].split("]")[0].strip())
            if factor > 0:
                unit_m = factor
        except (IndexError, ValueError):
            pass
    return kind, unit_m


def _geo_from_sidecar(image_path: str) -> GeoInfo | None:
    world = _find_sidecar(image_path, _WORLD_SUFFIXES)
    if world is None:
        return None
    try:
        with open(world, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        aff = Affine.from_world_file(lines)
    except (OSError, ValueError) as e:
        log.warning("[geo] 世界文件解析失败 %s: %s", world, e)
        return None

    crs_kind, unit_m, origin_lat = "unknown", 1.0, None
    prj = _find_sidecar(image_path, (".prj",))
    if prj is not None:
        try:
            with open(prj, encoding="utf-8") as fh:
                crs_kind, unit_m = _parse_prj(fh.read())
        except OSError:
            pass
    if crs_kind == "unknown":
        # 无 .prj 时用量级启发式: 像元 < 0.01 极可能是度(地理坐标系)。
        if aff.pixel_size_x() < 0.01:
            crs_kind = "geographic"
            log.warning("[geo] 无 .prj,依像元尺寸启发式判为地理坐标系(经纬度)。")
        else:
            crs_kind = "projected"
    if crs_kind == "geographic":
        origin_lat = aff.f  # 世界文件 F = 上左像元中心的 y(纬度)
    return GeoInfo(
        transform=aff, crs_kind=crs_kind, linear_unit_m=unit_m,
        origin_lat=origin_lat, source="world_file",
    )


# --------------------------------------------------------------------------
# GeoTIFF 内嵌标签解析(Pillow)
# --------------------------------------------------------------------------
def _parse_geokeys(geo_dir) -> dict:
    """GeoKeyDirectoryTag(34735): 4-short 头 + N*(KeyID,Loc,Count,Value)。返回 {KeyID: Value}。"""
    out: dict[int, int] = {}
    try:
        vals = [int(v) for v in geo_dir]
    except (TypeError, ValueError):
        return out
    if len(vals) < 4:
        return out
    n = vals[3]
    for i in range(n):
        off = 4 + i * 4
        if off + 3 >= len(vals):
            break
        key_id, loc, _count, value = vals[off:off + 4]
        if loc == 0:  # 值直接存于 Value_Offset
            out[key_id] = value
    return out


def _geo_from_geotiff_tags(image_path: str) -> GeoInfo | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(image_path) as im:
            tags = dict(getattr(im, "tag_v2", {}) or {})
    except (OSError, ValueError):
        return None
    if not tags:
        return None

    pixel_scale = tags.get(33550)       # ModelPixelScaleTag
    transformation = tags.get(34264)    # ModelTransformationTag
    tiepoint = tags.get(33922)          # ModelTiepointTag
    geo_dir = tags.get(34735)           # GeoKeyDirectoryTag

    if transformation is not None and len(transformation) >= 16:
        m = [float(v) for v in transformation]
        # 4x4 行主序: a=m0 b=m1 c=m3 ; d=m4 e=m5 f=m7
        aff = Affine(a=m[0], b=m[1], c=m[3], d=m[4], e=m[5], f=m[7])
    elif pixel_scale is not None and len(pixel_scale) >= 2:
        sx, sy = float(pixel_scale[0]), float(pixel_scale[1])
        ox = oy = 0.0
        if tiepoint is not None and len(tiepoint) >= 6:
            ox, oy = float(tiepoint[3]), float(tiepoint[4])
        aff = Affine.from_pixel_scale(sx, sy, ox, oy)
    else:
        return None

    crs_kind, unit_m, origin_lat = "unknown", 1.0, None
    keys = _parse_geokeys(geo_dir) if geo_dir is not None else {}
    model_type = keys.get(1024)  # GTModelTypeGeoKey: 1=Projected 2=Geographic
    if model_type == 1:
        crs_kind = "projected"
        unit_m = _EPSG_LINEAR_UNIT_M.get(keys.get(3076), 1.0)  # ProjLinearUnitsGeoKey
    elif model_type == 2:
        crs_kind = "geographic"
        origin_lat = aff.f
    else:
        # 无明确模型时用量级启发式。
        if aff.pixel_size_x() < 0.01:
            crs_kind, origin_lat = "geographic", aff.f
        else:
            crs_kind = "projected"
    return GeoInfo(
        transform=aff, crs_kind=crs_kind, linear_unit_m=unit_m,
        origin_lat=origin_lat, source="geotiff_tags",
    )


def _geo_from_rasterio(transform, crs) -> GeoInfo | None:
    if transform is None:
        return None
    try:
        aff = Affine.from_rasterio(transform)
    except (AttributeError, TypeError, ValueError):
        return None
    crs_kind, unit_m, origin_lat = "unknown", 1.0, None
    if crs is not None:
        try:
            if getattr(crs, "is_geographic", False):
                crs_kind, origin_lat = "geographic", aff.f
            else:
                crs_kind = "projected"
                lu = getattr(crs, "linear_units", None)
                if isinstance(lu, str) and lu.lower() in ("foot", "us-ft", "ft"):
                    unit_m = 0.3048
        except Exception:  # pragma: no cover - crs 实现差异兑底
            pass
    return GeoInfo(
        transform=aff, crs_kind=crs_kind, linear_unit_m=unit_m,
        origin_lat=origin_lat, source="rasterio",
    )


def resolve_geo(
    image_path: str | None,
    *,
    transform=None,
    crs=None,
) -> GeoInfo | None:
    """依次尝试 rasterio -> 世界文件 -> GeoTIFF 内嵌标签，均失败返回 None。"""
    info = _geo_from_rasterio(transform, crs)
    if info is not None:
        return info
    if not image_path or not os.path.isfile(image_path):
        return None
    info = _geo_from_sidecar(image_path)
    if info is not None:
        return info
    return _geo_from_geotiff_tags(image_path)


def compute_tract_geometry(
    image_path: str | None,
    width: int | None,
    height: int | None,
    *,
    transform=None,
    crs=None,
) -> dict | None:
    """解析地理信息并结合像素尺寸算出地块几何。

    返回 {gsd, geo_area, area_unit, pixel_w, pixel_h, crs_kind, geo_source};
    无法获取仿射变换或面积时返回 None。
    """
    geo = resolve_geo(image_path, transform=transform, crs=crs)
    if geo is None:
        return None
    pa = geo.pixel_area_m2()
    if pa is None or pa <= 0:
        return None
    out = {
        "gsd": geo.gsd_m(),
        "area_unit": "m2",
        "pixel_w": int(width) if width else None,
        "pixel_h": int(height) if height else None,
        "crs_kind": geo.crs_kind,
        "geo_source": geo.source,
    }
    if width and height:
        out["geo_area"] = pa * int(width) * int(height)
    else:
        out["geo_area"] = None
    log.info(
        "[geo] 解析成功(源=%s,坐标系=%s): GSD=%.4fm 像元面积=%.4f㎡ 地块面积=%s㎡",
        geo.source, geo.crs_kind, out["gsd"] or -1, pa,
        f"{out['geo_area']:.1f}" if out["geo_area"] else "?",
    )
    return out
