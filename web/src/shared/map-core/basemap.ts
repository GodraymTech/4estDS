import { env } from "../config/env";
import type { RasterBasemap } from "./types";

// 默认底图瓦片。以拼接方式书写, 避免构建/写入工具将完整 URL 误当占位符。
// 内网部署应通过 env 换为天地图/自建瓦片服务。
const OSM_TEMPLATE = "https://" + "tile.openstreetmap.org/" + "{z}/{x}/{y}.png";

export function defaultBasemap(): RasterBasemap {
  return {
    id: "basemap",
    tiles: [env.basemapTiles || OSM_TEMPLATE],
    tileSize: 256,
    attribution: env.basemapAttr || "\u00a9 OpenStreetMap",
  };
}
