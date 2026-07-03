import type { BBox, GeoJson } from "./types";

// 由 FeatureCollection 算包围盒(处理 Point/Polygon 嵌套坐标)。纯函数, 易测。
export function boundsOf(fc: GeoJson): BBox | null {
  let minX = Infinity,
    minY = Infinity,
    maxX = -Infinity,
    maxY = -Infinity;
  const visit = (coords: unknown): void => {
    const arr = coords as number[];
    if (typeof arr[0] === "number") {
      const [x, y] = arr;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    } else {
      for (const c of coords as unknown[]) visit(c);
    }
  };
  const features = (
    fc as { features?: Array<{ geometry?: { coordinates?: unknown } }> }
  ).features;
  for (const f of features ?? []) {
    if (f.geometry?.coordinates) visit(f.geometry.coordinates);
  }
  if (!isFinite(minX)) return null;
  return [
    [minX, minY],
    [maxX, maxY],
  ];
}
