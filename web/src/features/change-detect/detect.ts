import type { FeatureCollection, GeoFeature } from "../../shared/api";
import { haversineMeters, polygonAreaMeters } from "../../shared/lib/geodesy";
import { liveFeatureCollection } from "../../shared/lib/species";

// 逐图斑空间变化检测(客户端近似)。
// 语义: 单木树冠不位移, 两期同一棵树的冠应近乎重合。
// 因此用「质心最近邻 + 冠幅等效半径阈值」贪婪匹配, 避免引入多边形布尔运算库。
// 匹配 = 保留; 仅 after 匹上 = 新增(造林/扩展); 仅 before 匹上 = 消失(枯死/砸伐)。
export type ChangeType = "added" | "lost" | "retained";

export interface DetectResult {
  features: FeatureCollection; // 每个要素带 properties.changeType
  addedCount: number;
  lostCount: number;
  retainedCount: number;
  addedArea: number; // 平方米
  lostArea: number;
  retainedArea: number;
}

interface Crown {
  x: number;
  y: number;
  r: number; // 等效半径(m)
  area: number; // m²
  f: GeoFeature;
}

function outerRing(f: GeoFeature): number[][] | null {
  const g = f.geometry as { type?: string; coordinates?: unknown } | null;
  if (!g || !g.coordinates) return null;
  if (g.type === "Polygon") return (g.coordinates as number[][][])[0] ?? null;
  if (g.type === "MultiPolygon") {
    return (g.coordinates as number[][][][])[0]?.[0] ?? null;
  }
  return null;
}

function toCrown(f: GeoFeature): Crown | null {
  const ring = outerRing(f);
  if (!ring || ring.length === 0) return null;
  let sx = 0;
  let sy = 0;
  for (const p of ring) {
    sx += p[0];
    sy += p[1];
  }
  const n = ring.length;
  const area = polygonAreaMeters([ring]);
  const r = Math.sqrt(Math.max(area, 1) / Math.PI);
  return { x: sx / n, y: sy / n, r, area, f };
}

function tag(f: GeoFeature, changeType: ChangeType): GeoFeature {
  return { ...f, properties: { ...f.properties, changeType } };
}

export function detectPolygonChanges(
  before?: FeatureCollection,
  after?: FeatureCollection,
): DetectResult {
  const beforeC = (liveFeatureCollection(before)?.features ?? [])
    .map(toCrown)
    .filter((c): c is Crown => c !== null);
  const afterC = (liveFeatureCollection(after)?.features ?? [])
    .map(toCrown)
    .filter((c): c is Crown => c !== null);

  const usedBefore = new Set<number>();
  const feats: GeoFeature[] = [];
  let addedCount = 0;
  let retainedCount = 0;
  let addedArea = 0;
  let retainedArea = 0;

  for (const a of afterC) {
    let best = -1;
    let bestD = Infinity;
    for (let i = 0; i < beforeC.length; i++) {
      if (usedBefore.has(i)) continue;
      const b = beforeC[i];
      const d = haversineMeters([a.x, a.y], [b.x, b.y]);
      if (d < bestD && d <= a.r + b.r) {
        bestD = d;
        best = i;
      }
    }
    if (best >= 0) {
      usedBefore.add(best);
      retainedCount++;
      retainedArea += a.area;
      feats.push(tag(a.f, "retained"));
    } else {
      addedCount++;
      addedArea += a.area;
      feats.push(tag(a.f, "added"));
    }
  }

  let lostCount = 0;
  let lostArea = 0;
  for (let i = 0; i < beforeC.length; i++) {
    if (usedBefore.has(i)) continue;
    lostCount++;
    lostArea += beforeC[i].area;
    feats.push(tag(beforeC[i].f, "lost"));
  }

  return {
    features: { type: "FeatureCollection", features: feats },
    addedCount,
    lostCount,
    retainedCount,
    addedArea,
    lostArea,
    retainedArea,
  };
}

function onlyType(fc: FeatureCollection, t: ChangeType): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: fc.features.filter((f) => f.properties.changeType === t),
  };
}

// 按变化类型拆分(供地图分层上色)。
export function splitByChange(
  fc: FeatureCollection,
): Record<ChangeType, FeatureCollection> {
  return {
    added: onlyType(fc, "added"),
    lost: onlyType(fc, "lost"),
    retained: onlyType(fc, "retained"),
  };
}
