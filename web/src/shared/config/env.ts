// 集中管理前端环境变量(单一真相)。业务代码只读此处, 不直接碰 import.meta.env。
export const env = {
  /** API 基础路径: 生产由 nginx 反代到 /api/v1, 开发由 vite proxy 代理。 */
  apiBase: (import.meta.env.VITE_API_BASE as string) || "/api/v1",
  /** 底图瓦片模板(内网可换天地图/自建 TiTiler); 为空则由 map-core 回退默认。 */
  basemapTiles: (import.meta.env.VITE_BASEMAP_TILES as string) || "",
  /** 底图版权声明。 */
  basemapAttr: (import.meta.env.VITE_BASEMAP_ATTR as string) || "",
} as const;
