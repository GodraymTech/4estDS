// map-core 对外的中立地理类型(不泄露 MapLibre 类型, 便于日后换引擎)。
export type LngLat = [number, number];

/** 包围盒: [[minX, minY], [maxX, maxY]]。 */
export type BBox = [LngLat, LngLat];

export interface GeoJson {
  type: string;
  [k: string]: unknown;
}

export interface RasterBasemap {
  id: string;
  tiles: string[];
  tileSize?: number;
  attribution?: string;
}

export type VectorLayerKind = "point" | "polygon";

export interface GeoJsonLayerSpec {
  id: string;
  kind: VectorLayerKind;
  data: GeoJson;
  /** 颜色引用设计令牌语义值(由调用方传入), 维持单一真相。 */
  color?: string;
}

/** 相机状态(中立): 用于时相卷帘的双图联动同步。 */
export interface Camera {
  center: LngLat;
  zoom: number;
  bearing: number;
  pitch: number;
}

export interface MapInitOptions {
  container: HTMLElement;
  center: LngLat;
  zoom: number;
  basemap: RasterBasemap;
  /** 是否可交互(卷帘的跟随图为 false, 仅随主图相机同步)。 */
  interactive?: boolean;
}

export type MapCoreEvent =
  "ready" | "featureClick" | "featureHover" | "move" | "moveend";

export type MapCoreHandler = (payload: unknown) => void;
