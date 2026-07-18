import type {
  EffectiveAreaGeometry,
  EffectiveAreaImportResponse,
  EffectiveAreaResponse,
  EffectiveAreaRing,
  FeatureCollection,
} from "../../shared/api";

export type { EffectiveAreaGeometry } from "../../shared/api";
export type EffectiveArea = EffectiveAreaResponse;
export type EffectiveAreaImportResult = EffectiveAreaImportResponse;

export interface EffectiveAreaApiFailure {
  status?: number;
  code?: string;
  message?: string;
}

export function formatHm2(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(1) : "—";
}

export function formatAreaLedgerValue(
  tractAreaHm2: number | null | undefined,
  effectiveAreaHm2: number | null | undefined,
): string {
  return `${formatHm2(tractAreaHm2)}（${formatHm2(effectiveAreaHm2)}）`;
}

export function geometryVertexCount(geometry: EffectiveAreaGeometry | null | undefined): number {
  if (!geometry) return 0;
  const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  return polygons.reduce(
    (total, polygon) => total + polygon.reduce((ringTotal, ring) => ringTotal + openRingLength(ring), 0),
    0,
  );
}

export function cloneGeometry(geometry: EffectiveAreaGeometry): EffectiveAreaGeometry {
  return JSON.parse(JSON.stringify(geometry)) as EffectiveAreaGeometry;
}

export function buildInvalidAreaMask(
  boundary: EffectiveAreaGeometry,
  effective: EffectiveAreaGeometry,
): FeatureCollection {
  const boundaryPolygons = boundary.type === "Polygon" ? [boundary.coordinates] : boundary.coordinates;
  const effectivePolygons = effective.type === "Polygon" ? [effective.coordinates] : effective.coordinates;
  const outsideFeatures = boundaryPolygons.map((polygon) => ({
    type: "Feature" as const,
    properties: {},
    geometry: {
      type: "Polygon",
      coordinates: [
        polygon[0],
        ...polygon.slice(1),
        ...effectivePolygons
          .map((candidate) => candidate[0])
          .filter((ring) => ring[0] && pointInRing(ring[0], polygon[0])),
      ],
    },
  }));
  const effectiveHoleFeatures = effectivePolygons.flatMap((polygon) =>
    polygon.slice(1).map((ring) => ({
      type: "Feature" as const,
      properties: {},
      geometry: { type: "Polygon", coordinates: [ring] },
    })),
  );
  return {
    type: "FeatureCollection",
    features: [...outsideFeatures, ...effectiveHoleFeatures],
  };
}

export function effectiveAreaErrorMessage(error: EffectiveAreaApiFailure): string {
  if (error.status === 409 || error.code === "effective_area_conflict") {
    return "有效区域已被其他操作更新，请重新加载后再保存。";
  }
  if (error.code === "outside_boundary") {
    return "有效区域超出地块边界，请确认裁剪后再次保存。";
  }
  if (error.status === 422) {
    return error.message || "有效区域不符合几何或坐标系要求，请检查后重试。";
  }
  return error.message || "有效区域操作失败，请稍后重试。";
}

function openRingLength(ring: EffectiveAreaRing): number {
  if (ring.length < 2) return ring.length;
  const first = ring[0];
  const last = ring[ring.length - 1];
  return first[0] === last[0] && first[1] === last[1] ? ring.length - 1 : ring.length;
}

function pointInRing(point: number[], ring: EffectiveAreaRing): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if ((yi > point[1]) !== (yj > point[1])
      && point[0] < ((xj - xi) * (point[1] - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}
