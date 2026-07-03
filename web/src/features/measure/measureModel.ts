import type { GeoJson, LngLat } from "../../shared/map-core";
import {
  polygonAreaMeters,
  polylineLengthMeters,
} from "../../shared/lib/geodesy";

export type MeasureMode = "idle" | "distance" | "area";

export interface MeasureResult {
  length: number; // 米(distance: 折线长; area: 周长)
  area: number; // 平方米(area 模式)
  points: number;
}

// 根据模式与取点计算长度/面积(测地)。
export function computeMeasure(
  mode: MeasureMode,
  coords: LngLat[],
): MeasureResult {
  if (mode === "distance") {
    return {
      length: polylineLengthMeters(coords),
      area: 0,
      points: coords.length,
    };
  }
  if (mode === "area" && coords.length >= 3) {
    const ring = [...coords, coords[0]];
    return {
      length: polylineLengthMeters(ring),
      area: polygonAreaMeters([ring.map((c) => [c[0], c[1]])]),
      points: coords.length,
    };
  }
  return { length: 0, area: 0, points: coords.length };
}

export function buildPointsGeoJson(coords: LngLat[]): GeoJson {
  return {
    type: "FeatureCollection",
    features: coords.map((c, i) => ({
      type: "Feature",
      properties: { i },
      geometry: { type: "Point", coordinates: c },
    })),
  };
}

export function buildLineGeoJson(coords: LngLat[]): GeoJson {
  const features =
    coords.length >= 2
      ? [
          {
            type: "Feature",
            properties: {},
            geometry: { type: "LineString", coordinates: coords },
          },
        ]
      : [];
  return { type: "FeatureCollection", features };
}

export function buildAreaGeoJson(coords: LngLat[]): GeoJson {
  if (coords.length < 3) return { type: "FeatureCollection", features: [] };
  const ring = [...coords, coords[0]];
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: {},
        geometry: { type: "Polygon", coordinates: [ring] },
      },
    ],
  };
}

export function formatLength(m: number): string {
  if (m <= 0) return "-";
  return m >= 1000 ? (m / 1000).toFixed(2) + " km" : m.toFixed(1) + " m";
}

export function formatArea(m2: number): string {
  if (m2 <= 0) return "-";
  if (m2 >= 1000000) return (m2 / 1000000).toFixed(3) + " km\u00b2";
  const ha = m2 / 10000;
  return ha >= 1 ? ha.toFixed(3) + " ha" : m2.toFixed(1) + " m\u00b2";
}
