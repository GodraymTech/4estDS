import type { Tract } from "../../shared/api";
import { type BBox, type LngLat, isValidLngLat } from "../../shared/map-core";

// 地块代表点: 优先用后端回填的质心经纬度; 缺失或超出合法地理经纬度范围则返回 null(不伪造坐标)。
export function tractCenter(t: Tract): LngLat | null {
  if (typeof t.center_lng === "number" && typeof t.center_lat === "number") {
    const candidate: LngLat = [t.center_lng, t.center_lat];
    if (isValidLngLat(candidate)) return candidate;
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
