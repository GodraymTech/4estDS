import type {
  BBox,
  Camera,
  GeoJson,
  GeoJsonLayerSpec,
  LngLat,
  MapCoreEvent,
  MapCoreHandler,
  MapInitOptions,
} from "./types";

/**
 * 地图能力的抽象契约 —— 防腐层(Anti-Corruption Layer)。
 *
 * 业务(features/entities/pages)只依赖此接口, 不直接接触 MapLibre —— 依赖倒置(DIP/SOLID)。
 * 日后换底图引擎(天地图 / 内网瓦片 / Cesium)只需另写一个实现, 上层零改动。
 * 与后端 contracts 同一防腐思想。
 */
export interface MapController {
  init(opts: MapInitOptions): Promise<void>;
  destroy(): void;
  isReady(): boolean;

  /** 新增/替换一个 GeoJSON 矢量图层(单木点 / 树冠面)。 */
  setGeoJsonLayer(spec: GeoJsonLayerSpec): void;
  removeLayer(id: string): void;
  /** 仅更新已有图层的数据(不重建图层)。 */
  setData(layerId: string, data: GeoJson): void;

  fitBounds(bounds: BBox, padding?: number): void;
  flyTo(center: LngLat, zoom: number): void;

  /** 相机同步(时相卷帘的双图联动): 读取与无动画套用当前视口。 */
  getCamera(): Camera;
  jumpTo(camera: Camera): void;

  on(event: MapCoreEvent, handler: MapCoreHandler): void;
}
