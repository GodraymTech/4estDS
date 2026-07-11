import type {
  BBox,
  Camera,
  FitBoundsOptions,
  GeoJson,
  GeoJsonLayerSpec,
  LngLat,
  MapCoreEvent,
  MapCoreHandler,
  MapInitOptions,
  MarkerSpec,
  RasterOverlaySpec,
  RasterBasemap,
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

  /** 替换全部 HTML 标记(倒水滴地块图标等)。 */
  setMarkers(markers: MarkerSpec[]): void;
  clearMarkers(): void;

  fitBounds(bounds: BBox, options?: number | FitBoundsOptions): void;
  flyTo(center: LngLat, zoom: number): void;
  zoomIn(): void;
  zoomOut(): void;
  getZoom(): number;
  getBounds(): BBox;
  setMaxBounds(bounds: BBox | null): void;
  setMinZoom(zoom: number | null): void;

  /** 相机同步(时相卷帘的双图联动): 读取与无动画套用当前视口。 */
  getCamera(): Camera;
  jumpTo(camera: Camera): void;

  /** 设置地图光标(如量算时的 crosshair); 传 null 恢复默认。 */
  setCursor(cursor: string | null): void;

  /** 热替换底图瓦片(多时相真影像刷开): 复用同一 raster source, 仅换 tiles。 */
  setBasemap(basemap: RasterBasemap): void;
  /** 添加/替换一个 raster 叠加层(真影像、路网等)。 */
  setRasterOverlay(id: string, overlay: RasterOverlaySpec): void;
  removeRasterOverlay(id: string): void;

  /** 订阅事件, 返回退订函数(用于量算等临时交互的清理)。 */
  on(event: MapCoreEvent, handler: MapCoreHandler): () => void;
}
