import type { FeatureCollection, GeoFeature } from "../../shared/api";
import { polygonAreaMeters } from "../../shared/lib/geodesy";

// 变化量化指标(聚合总量对比)。
// 说明: 这是两期树冠的总量对比(株数/总面积), 非逐图斑的空间变化检测。
// 逐图斑新增/消失(真正的变化图斑)由 change-detect 空间叠分模块处理。
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

function featureArea(f: GeoFeature): number {
  const geom = f.geometry as { type?: string; coordinates?: unknown } | null;
  if (!geom || !geom.coordinates) return 0;
  if (geom.type === "Polygon") {
    return polygonAreaMeters(geom.coordinates as number[][][]);
  }
  if (geom.type === "MultiPolygon") {
    return (geom.coordinates as number[][][][]).reduce(
      (s, poly) => s + polygonAreaMeters(poly),
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
