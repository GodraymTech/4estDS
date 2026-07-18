import turfArea from "@turf/area";
import turfBbox from "@turf/bbox";
import turfDifference from "@turf/difference";
import { feature, featureCollection } from "@turf/helpers";
import turfUnion from "@turf/union";
import type { EffectiveAreaGeometry, EffectiveAreaRing } from "../../shared/api";

export function areaHm2(geometry: EffectiveAreaGeometry): number {
  return turfArea(feature(geometry as never)) / 10_000;
}

export function geometryBbox(geometry: EffectiveAreaGeometry): [number, number, number, number] {
  return turfBbox(feature(geometry as never)) as [number, number, number, number];
}

export function mergeGeometry(
  left: EffectiveAreaGeometry,
  right: EffectiveAreaGeometry,
): EffectiveAreaGeometry {
  const result = turfUnion(featureCollection([
    feature(left as never),
    feature(right as never),
  ]) as never);
  return result?.geometry as EffectiveAreaGeometry ?? combineGeometry(left, right);
}

export function subtractGeometry(
  base: EffectiveAreaGeometry,
  mask: EffectiveAreaGeometry,
): EffectiveAreaGeometry {
  const result = turfDifference(featureCollection([
    feature(base as never),
    feature(mask as never),
  ]) as never);
  if (!result) throw new Error("几何操作后有效区域为空");
  return result.geometry as EffectiveAreaGeometry;
}

export function splitGeometryByLine(
  geometry: EffectiveAreaGeometry,
  line: number[][],
): EffectiveAreaGeometry {
  const start = line[0];
  const end = line[line.length - 1];
  if (!start || !end || samePosition(start, end)) return geometry;
  const source = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  const parts: EffectiveAreaRing[][] = [];
  for (const polygon of source) {
    for (const keepLeft of [true, false]) {
      const exterior = clipRing(polygon[0], start, end, keepLeft);
      if (exterior.length < 4) continue;
      let part: EffectiveAreaGeometry = { type: "Polygon", coordinates: [exterior] };
      for (const hole of polygon.slice(1)) {
        try {
          part = subtractGeometry(part, { type: "Polygon", coordinates: [hole] });
        } catch {
          part = { type: "Polygon", coordinates: [exterior] };
        }
      }
      parts.push(...polygonsOf(part));
    }
  }
  if (parts.length < 2) return geometry;
  return { type: "MultiPolygon", coordinates: parts };
}

export function combineGeometry(
  left: EffectiveAreaGeometry,
  right: EffectiveAreaGeometry,
): EffectiveAreaGeometry {
  return { type: "MultiPolygon", coordinates: [...polygonsOf(left), ...polygonsOf(right)] };
}

function polygonsOf(geometry: EffectiveAreaGeometry): EffectiveAreaRing[][] {
  return geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
}

function clipRing(
  ring: EffectiveAreaRing,
  start: number[],
  end: number[],
  keepLeft: boolean,
): EffectiveAreaRing {
  const input = samePosition(ring[0], ring[ring.length - 1]) ? ring.slice(0, -1) : [...ring];
  const output: EffectiveAreaRing = [];
  for (let index = 0; index < input.length; index += 1) {
    const current = input[index];
    const next = input[(index + 1) % input.length];
    const currentSide = side(current, start, end);
    const nextSide = side(next, start, end);
    const currentInside = keepLeft ? currentSide >= 0 : currentSide <= 0;
    const nextInside = keepLeft ? nextSide >= 0 : nextSide <= 0;
    if (currentInside) output.push(current);
    if (currentInside !== nextInside) {
      const ratio = currentSide / (currentSide - nextSide);
      output.push([
        current[0] + ratio * (next[0] - current[0]),
        current[1] + ratio * (next[1] - current[1]),
      ]);
    }
  }
  if (output.length >= 3) output.push([...output[0]]);
  return output;
}

function side(point: number[], start: number[], end: number[]): number {
  return (end[0] - start[0]) * (point[1] - start[1])
    - (end[1] - start[1]) * (point[0] - start[0]);
}

function samePosition(left?: number[], right?: number[]): boolean {
  return Boolean(left && right && left[0] === right[0] && left[1] === right[1]);
}
