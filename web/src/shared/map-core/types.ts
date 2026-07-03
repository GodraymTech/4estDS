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

export type VectorLayerKind = "point" | "polygon" | "line";

export interface GeoJsonLayerSpec {
  id: string;
  kind: VectorLayerKind;
  data: GeoJson;
  /** 颜色引用设计令牌语义值(由调用方传入), 维持单一真相。 */
  color?: string;
}

/**
 * HTML 标记规格: 业务自建 DOM 元素(如倒水滴图标)并自行绑定交互,
 * map-core 仅负责把它定位到经纬度。形状/交互属于设计层, 不下沉到防腐层。
 */
export interface MarkerSpec {
  id: string;
  lngLat: LngLat;
  element: HTMLElement;
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
  "ready" | "featureClick" | "featureHover" | "move" | "moveend" | "mapClick";

export type MapCoreHandler = (payload: unknown) => void;
