import { env } from "../config/env";
import type { RasterBasemap } from "./types";

// 以拼接方式书写 URL, 避免构建/写入工具将完整模板误当占位符。
const OSM_TEMPLATE = "https://" + "tile.openstreetmap.org/" + "{z}/{x}/{y}.png";
const ESRI_IMAGERY =
  "https://" +
  "server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/" +
  "{z}/{y}/{x}";
const CARTO_LIGHT =
  "https://" +
  "a.basemaps.cartocdn.com/light_all/" +
  "{z}/{x}/{y}.png";

export interface BasemapOption extends RasterBasemap {
  label: string;
  kind: "road" | "satellite" | "light";
}

export const BASEMAPS: BasemapOption[] = [
  {
    id: "satellite",
    label: "卫星",
    kind: "satellite",
    tiles: [ESRI_IMAGERY],
    tileSize: 256,
    attribution: "Tiles \u00a9 Esri",
  },
  {
    id: "osm-road",
    label: "路网",
    kind: "road",
    tiles: [env.basemapTiles || OSM_TEMPLATE],
    tileSize: 256,
    attribution: env.basemapAttr || "\u00a9 OpenStreetMap",
  },
  {
    id: "light",
    label: "浅色",
    kind: "light",
    tiles: [CARTO_LIGHT],
    tileSize: 256,
    attribution: "\u00a9 OpenStreetMap \u00a9 CARTO",
  },
];

export const ROAD_OVERLAY: RasterBasemap = {
  id: "road-overlay",
  tiles: [env.roadOverlayTiles || OSM_TEMPLATE],
  tileSize: 256,
  attribution: env.roadOverlayAttr || "\u00a9 OpenStreetMap",
};

// 由后端多时相真影像瓦片构造底图(时相卷帘刷开真影像)。
export function rasterBasemap(
  tiles: string[],
  opts?: {
    id?: string;
    tileSize?: number;
    attribution?: string;
    minZoom?: number | null;
    maxZoom?: number | null;
  },
): RasterBasemap {
  return {
    id: opts?.id ?? "basemap",
    tiles,
    tileSize: opts?.tileSize ?? 256,
    attribution: opts?.attribution ?? "",
    minZoom: opts?.minZoom ?? undefined,
    maxZoom: opts?.maxZoom ?? undefined,
  };
}

export function defaultBasemap(): RasterBasemap {
  return rasterBasemap(basemapById(env.defaultBasemapId).tiles, {
    attribution: basemapById(env.defaultBasemapId).attribution,
  });
}

export function basemapById(id: string): BasemapOption {
  return BASEMAPS.find((b) => b.id === id) ?? BASEMAPS[0];
}
