import type { BBox, LngLat } from "../map-core/types";

function parseLngLat(value: string | undefined, fallback: LngLat): LngLat {
  const parts = (value || "").split(",").map((v) => Number(v.trim()));
  if (parts.length === 2 && parts.every(Number.isFinite)) {
    return [parts[0], parts[1]];
  }
  return fallback;
}

function parseBBox(value: string | undefined, fallback: BBox): BBox {
  const parts = (value || "").split(",").map((v) => Number(v.trim()));
  if (parts.length === 4 && parts.every(Number.isFinite)) {
    return [
      [parts[0], parts[1]],
      [parts[2], parts[3]],
    ];
  }
  return fallback;
}

function parseNumber(value: string | undefined, fallback: number): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

// 集中管理前端环境变量(单一真相)。业务代码只读此处, 不直接碰 import.meta.env。
export const env = {
  /** API 基础路径: 生产由 nginx 反代到 /api/v1, 开发由 vite proxy 代理。 */
  apiBase: (import.meta.env.VITE_API_BASE as string) || "/api/v1",
  /** 底图瓦片模板(内网可换天地图/自建 TiTiler); 为空则由 map-core 回退默认。 */
  basemapTiles: (import.meta.env.VITE_BASEMAP_TILES as string) || "",
  /** 底图版权声明。 */
  basemapAttr: (import.meta.env.VITE_BASEMAP_ATTR as string) || "",
  /** 默认底图: satellite | osm-road | light。 */
  defaultBasemapId:
    (import.meta.env.VITE_DEFAULT_BASEMAP_ID as string) || "satellite",
  /** 可独立开关的路网瓦片。 */
  roadOverlayTiles: (import.meta.env.VITE_ROAD_OVERLAY_TILES as string) || "",
  roadOverlayAttr: (import.meta.env.VITE_ROAD_OVERLAY_ATTR as string) || "",
  /** 总观视野: 默认广东省。region 决定省界遮罩，center/bounds 可覆盖默认相机。 */
  overviewRegion: (import.meta.env.VITE_OVERVIEW_REGION as string) || "广东含海域",
  overviewCenter: parseLngLat(
    import.meta.env.VITE_OVERVIEW_CENTER as string | undefined,
    [113.27, 23.13],
  ),
  overviewZoom: parseNumber(
    import.meta.env.VITE_OVERVIEW_ZOOM as string | undefined,
    7,
  ),
  overviewMinZoom: parseNumber(
    import.meta.env.VITE_OVERVIEW_MIN_ZOOM as string | undefined,
    6.2,
  ),
  overviewBounds: parseBBox(
    import.meta.env.VITE_OVERVIEW_BOUNDS as string | undefined,
    [
      [109.35, 20.05],
      [117.35, 25.55],
    ],
  ),
  maxZoom: parseNumber(import.meta.env.VITE_MAX_ZOOM as string | undefined, 25),
} as const;

const STORAGE_ENDPOINT_KEY = "FORESTDS_ENDPOINT_URL";
const STORAGE_OFFLINE_KEY = "FORESTDS_OFFLINE_MODE";

export const DEFAULT_LOCAL_ENDPOINT = "http://localhost:8000";

export function getStoredEndpoint(): string {
  try {
    return localStorage.getItem(STORAGE_ENDPOINT_KEY)?.trim() || "";
  } catch {
    return "";
  }
}

export function setStoredEndpoint(url: string | null): void {
  try {
    if (!url || !url.trim()) {
      localStorage.removeItem(STORAGE_ENDPOINT_KEY);
    } else {
      localStorage.setItem(STORAGE_ENDPOINT_KEY, url.trim());
    }
  } catch {
    /* ignore */
  }
}

export function getOfflineMode(): boolean {
  try {
    return localStorage.getItem(STORAGE_OFFLINE_KEY) === "true";
  } catch {
    return false;
  }
}

export function setOfflineMode(offline: boolean): void {
  try {
    localStorage.setItem(STORAGE_OFFLINE_KEY, String(offline));
  } catch {
    /* ignore */
  }
}

export function resolveApiUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  const custom = getStoredEndpoint();
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;

  if (custom) {
    const baseUrl = custom.replace(/\/+$/, "");
    if (normalizedPath.startsWith("/api/v1") || normalizedPath === "/healthz" || normalizedPath === "/health") {
      return `${baseUrl}${normalizedPath}`;
    }
    return `${baseUrl}/api/v1${normalizedPath}`;
  }

  const defaultBase = env.apiBase.replace(/\/+$/, "");
  if (normalizedPath.startsWith("/api/v1")) {
    return normalizedPath;
  }
  return `${defaultBase}${normalizedPath}`;
}
