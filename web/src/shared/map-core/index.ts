// map-core 公共出口。业务只从此导入, 不触及具体实现文件。
export type {
  BBox,
  Camera,
  GeoJson,
  GeoJsonLayerSpec,
  LngLat,
  MapCoreEvent,
  MapInitOptions,
  RasterBasemap,
  VectorLayerKind,
} from "./types";
export type { MapController } from "./MapController";
export { MapLibreController } from "./MapLibreController";
export { defaultBasemap } from "./basemap";
export { boundsOf } from "./geo";

import { MapLibreController } from "./MapLibreController";
import type { MapController } from "./MapController";

// 工厂: 业务通过它获取控制器, 不直接 new 具体实现(依赖倒置)。
export function createMapController(): MapController {
  return new MapLibreController();
}
