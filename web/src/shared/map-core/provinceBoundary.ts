import guangdong from "./province-boundaries/guangdong.json";
import type { BBox, GeoJson, LngLat } from "./types";

type Ring = LngLat[];

const BOUNDARIES: Record<string, GeoJson> = {
  "440000": guangdong as GeoJson,
  guangdong: guangdong as GeoJson,
  "广东": guangdong as GeoJson,
  "广东省": guangdong as GeoJson,
};

const WORLD_RING: Ring = [
  [-180, -85],
  [180, -85],
  [180, 85],
  [-180, 85],
  [-180, -85],
];

export function provinceBoundaryByName(name: string): GeoJson | null {
  const key = normalizeProvinceName(name);
  return BOUNDARIES[key] ?? BOUNDARIES[name] ?? null;
}

export function provinceBounds(boundary: GeoJson | null): BBox | null {
  if (!boundary) return null;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;

  const visit = (coords: unknown): void => {
    const arr = coords as unknown[];
    if (typeof arr[0] === "number") {
      const [x, y] = arr as number[];
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
      return;
    }
    for (const item of arr) visit(item);
  };

  for (const feature of featuresOf(boundary)) {
    if (feature.geometry?.coordinates) visit(feature.geometry.coordinates);
  }
  if (!Number.isFinite(minX)) return null;
  return [
    [minX, minY],
    [maxX, maxY],
  ];
}

export function provinceMask(boundary: GeoJson | null, fallback: BBox): GeoJson {
  if (!boundary) return bboxMask(fallback);
  const holes = extractExteriorRings(boundary);
  if (holes.length === 0) return bboxMask(fallback);
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: {},
        geometry: {
          type: "Polygon",
          coordinates: [
            orientRing(WORLD_RING, false),
            ...holes.map((ring) => orientRing(closeRing(ring), true)),
          ],
        },
      },
    ],
  };
}

function normalizeProvinceName(name: string): string {
  const raw = name.trim();
  const lower = raw.toLowerCase();
  if (lower === "guangdong") return "guangdong";
  if (/^\d{6}$/.test(raw)) return raw;
  return raw.endsWith("省") ? raw : raw + "省";
}

function featuresOf(boundary: GeoJson) {
  if (Array.isArray(boundary.features)) {
    return boundary.features as Array<{
      geometry?: { type?: string; coordinates?: unknown };
    }>;
  }
  return [
    {
      geometry: (boundary as { geometry?: { type?: string; coordinates?: unknown } }).geometry,
    },
  ];
}

function extractExteriorRings(boundary: GeoJson): Ring[] {
  const rings: Ring[] = [];
  for (const feature of featuresOf(boundary)) {
    const geometry = feature.geometry;
    if (!geometry?.coordinates) continue;
    if (geometry.type === "Polygon") {
      const polygon = geometry.coordinates as Ring[];
      if (polygon[0]) rings.push(polygon[0]);
    }
    if (geometry.type === "MultiPolygon") {
      const multi = geometry.coordinates as Ring[][];
      for (const polygon of multi) {
        if (polygon[0]) rings.push(polygon[0]);
      }
    }
  }
  return rings;
}

function bboxMask(bounds: BBox): GeoJson {
  const [[west, south], [east, north]] = bounds;
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: {},
        geometry: {
          type: "Polygon",
          coordinates: [
            orientRing(WORLD_RING, false),
            orientRing(
              [
                [west, south],
                [west, north],
                [east, north],
                [east, south],
                [west, south],
              ],
              true,
            ),
          ],
        },
      },
    ],
  };
}

function closeRing(ring: Ring): Ring {
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (!first || !last) return ring;
  if (first[0] === last[0] && first[1] === last[1]) return ring;
  return [...ring, first];
}

function orientRing(ring: Ring, clockwise: boolean): Ring {
  const closed = closeRing(ring);
  const isClockwise = signedArea(closed) < 0;
  return isClockwise === clockwise ? closed : [...closed].reverse();
}

function signedArea(ring: Ring): number {
  let area = 0;
  for (let i = 0; i < ring.length - 1; i += 1) {
    const [x1, y1] = ring[i];
    const [x2, y2] = ring[i + 1];
    area += x1 * y2 - x2 * y1;
  }
  return area / 2;
}
