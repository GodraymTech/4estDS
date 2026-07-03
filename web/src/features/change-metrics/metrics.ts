import type { FeatureCollection, GeoFeature } from "../../shared/api";

// 变化量化指标(聚合总量对比)。
// 说明: 这是两期树冠的总量对比(株数/总面积), 非逐图斑的空间变化检测。
// 逐图斑新增/消失(真正的变化图斑)需 GIS 空间叠分, 归为 P2 后端任务。
export interface ChangeMetrics {
  countBefore: number;
  countAfter: number;
  countDelta: number;
  countPct: number | null;
  areaBefore: number; // 平方米
  areaAfter: number;
  areaDelta: number;
  areaPct: number | null;
}

const EARTH_RADIUS = 6378137; // WGS84 赤道半径(m)

function toRad(deg: number): number {
  return (deg * Math.PI) / 180;
}

// 单个环的测地面积(球面, 与 turf ringArea 一致)。返回绝对值(m²)。
function ringArea(coords: number[][]): number {
  const len = coords.length;
  if (len <= 2) return 0;
  let total = 0;
  for (let i = 0; i < len; i++) {
    let lower: number, middle: number, upper: number;
    if (i === len - 2) {
      lower = len - 2;
      middle = len - 1;
      upper = 0;
    } else if (i === len - 1) {
      lower = len - 1;
      middle = 0;
      upper = 1;
    } else {
      lower = i;
      middle = i + 1;
      upper = i + 2;
    }
    const p1 = coords[lower];
    const p2 = coords[middle];
    const p3 = coords[upper];
    total += (toRad(p3[0]) - toRad(p1[0])) * Math.sin(toRad(p2[1]));
  }
  return Math.abs((total * EARTH_RADIUS * EARTH_RADIUS) / 2);
}

// 多边形面积 = 外环 - 内环(孔洞)。
function polygonArea(rings: number[][][]): number {
  if (rings.length === 0) return 0;
  let area = ringArea(rings[0]);
  for (let i = 1; i < rings.length; i++) area -= ringArea(rings[i]);
  return Math.max(area, 0);
}

function featureArea(f: GeoFeature): number {
  const geom = f.geometry as { type?: string; coordinates?: unknown } | null;
  if (!geom || !geom.coordinates) return 0;
  if (geom.type === "Polygon")
    return polygonArea(geom.coordinates as number[][][]);
  if (geom.type === "MultiPolygon") {
    return (geom.coordinates as number[][][][]).reduce(
      (s, poly) => s + polygonArea(poly),
      0,
    );
  }
  return 0;
}

function totalArea(fc?: FeatureCollection): number {
  if (!fc) return 0;
  return fc.features.reduce((s, f) => s + featureArea(f), 0);
}

function pct(before: number, delta: number): number | null {
  if (before === 0) return null;
  return (delta / before) * 100;
}

export function buildChangeMetrics(
  before?: FeatureCollection,
  after?: FeatureCollection,
): ChangeMetrics {
  const countBefore = before?.features.length ?? 0;
  const countAfter = after?.features.length ?? 0;
  const countDelta = countAfter - countBefore;
  const areaBefore = totalArea(before);
  const areaAfter = totalArea(after);
  const areaDelta = areaAfter - areaBefore;
  return {
    countBefore,
    countAfter,
    countDelta,
    countPct: pct(countBefore, countDelta),
    areaBefore,
    areaAfter,
    areaDelta,
    areaPct: pct(areaBefore, areaDelta),
  };
}

// m² → 公顷(保留两位小数)。
export function toHectares(sqm: number): number {
  return Math.round((sqm / 10000) * 100) / 100;
}
