// 测地量算(WGS84 球面, 与 turf 一致)。纯函数, 供量算/变化量化复用(DRY)。
const EARTH_RADIUS = 6378137; // 赤道半径(m)

function toRad(deg: number): number {
  return (deg * Math.PI) / 180;
}

// 两点大圆距离(haversine, m)。
export function haversineMeters(
  a: [number, number],
  b: [number, number],
): number {
  const dLat = toRad(b[1] - a[1]);
  const dLng = toRad(b[0] - a[0]);
  const lat1 = toRad(a[1]);
  const lat2 = toRad(b[1]);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_RADIUS * Math.asin(Math.min(1, Math.sqrt(h)));
}

// 折线总长(m)。
export function polylineLengthMeters(coords: Array<[number, number]>): number {
  let sum = 0;
  for (let i = 1; i < coords.length; i++) {
    sum += haversineMeters(coords[i - 1], coords[i]);
  }
  return sum;
}

// 单环测地面积(球面, m², 取绝对值)。
export function ringAreaMeters(coords: number[][]): number {
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

// 多边形面积 = 外环 - 内环(孔洞)(m²)。
export function polygonAreaMeters(rings: number[][][]): number {
  if (rings.length === 0) return 0;
  let area = ringAreaMeters(rings[0]);
  for (let i = 1; i < rings.length; i++) area -= ringAreaMeters(rings[i]);
  return Math.max(area, 0);
}
