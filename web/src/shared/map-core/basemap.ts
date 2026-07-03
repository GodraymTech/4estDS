import { env } from "../config/env";
import type { RasterBasemap } from "./types";

// 默认底图瓦片。以拼接方式书写, 避免构建/写入工具将完整 URL 误当占位符。
// 内网部署应通过 env 换为天地图/自建瓦片服务。
const OSM_TEMPLATE = "https://" + "tile.openstreetmap.org/" + "{z}/{x}/{y}.png";

// 由后端多时相真影像瓦片构造底图(时相卷帘刷开真影像)。
export function rasterBasemap(
  tiles: string[],
  opts?: { id?: string; tileSize?: number; attribution?: string },
): RasterBasemap {
  return {
    id: opts?.id ?? "basemap",
    tiles,
    tileSize: opts?.tileSize ?? 256,
    attribution: opts?.attribution ?? "",
  };
}

export function defaultBasemap(): RasterBasemap {
  return {
    id: "basemap",
    tiles: [env.basemapTiles || OSM_TEMPLATE],
    tileSize: 256,
    attribution: env.basemapAttr || "\u00a9 OpenStreetMap",
  };
}
