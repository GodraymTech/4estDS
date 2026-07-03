import type { Tract } from "../../shared/api";
import type { BBox, LngLat } from "../../shared/map-core";

// 地块代表点: 优先用后端回填的质心经纬度; 缺失则返回 null(不伪造坐标)。
export function tractCenter(t: Tract): LngLat | null {
  if (typeof t.center_lng === "number" && typeof t.center_lat === "number") {
    return [t.center_lng, t.center_lat];
  }
  return null;
}

// 由一组点算包围盒(用于总览图自适应视口)。
export function pointsBounds(pts: LngLat[]): BBox | null {
  if (pts.length === 0) return null;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const [x, y] of pts) {
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
  }
  return [
    [minX, minY],
    [maxX, maxY],
  ];
}
