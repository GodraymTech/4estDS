import maplibregl from "maplibre-gl";
import type {
  BBox,
  GeoJson,
  GeoJsonLayerSpec,
  LngLat,
  MapCoreEvent,
  MapCoreHandler,
  MapInitOptions,
} from "./types";
import type { MapController } from "./MapController";

const EMPTY: GeoJson = { type: "FeatureCollection", features: [] };
const DEFAULT_POINT_COLOR = "#0e6e63";
const DEFAULT_POLYGON_COLOR = "#3e8e5a";

/**
 * MapController 的 MapLibre 实现。
 * 所有 maplibre-gl 的依赖被封闭在本文件内; 业务层只面向 MapController 接口。
 */
export class MapLibreController implements MapController {
  private map: maplibregl.Map | null = null;
  private ready = false;
  private readonly rasterStyle: (
    basemap: MapInitOptions["basemap"],
  ) => maplibregl.StyleSpecification = (basemap) => ({
    version: 8,
    sources: {
      [basemap.id]: {
        type: "raster",
        tiles: basemap.tiles,
        tileSize: basemap.tileSize ?? 256,
        attribution: basemap.attribution ?? "",
      },
    },
    layers: [{ id: basemap.id, type: "raster", source: basemap.id }],
  });

  init(opts: MapInitOptions): Promise<void> {
    return new Promise((resolve) => {
      const map = new maplibregl.Map({
        container: opts.container,
        style: this.rasterStyle(opts.basemap),
        center: opts.center,
        zoom: opts.zoom,
      });
      map.addControl(new maplibregl.NavigationControl({}), "top-right");
      map.on("load", () => {
        this.ready = true;
        resolve();
      });
      this.map = map;
    });
  }

  destroy(): void {
    this.map?.remove();
    this.map = null;
    this.ready = false;
  }

  isReady(): boolean {
    return this.ready;
  }

  setGeoJsonLayer(spec: GeoJsonLayerSpec): void {
    const map = this.requireMap();
    if (!map.getSource(spec.id)) {
      map.addSource(spec.id, {
        type: "geojson",
        data: spec.data as GeoJSON.GeoJSON,
      });
    } else {
      this.setData(spec.id, spec.data);
    }
    if (map.getLayer(spec.id)) return;
    if (spec.kind === "point") {
      map.addLayer({
        id: spec.id,
        type: "circle",
        source: spec.id,
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 2, 16, 6],
          "circle-color": spec.color ?? DEFAULT_POINT_COLOR,
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 0.5,
          "circle-opacity": 0.85,
        },
      });
    } else {
      map.addLayer({
        id: spec.id,
        type: "fill",
        source: spec.id,
        paint: {
          "fill-color": spec.color ?? DEFAULT_POLYGON_COLOR,
          "fill-opacity": 0.25,
          "fill-outline-color": "#1a5c38",
        },
      });
    }
  }

  removeLayer(id: string): void {
    const map = this.map;
    if (!map) return;
    if (map.getLayer(id)) map.removeLayer(id);
    if (map.getSource(id)) map.removeSource(id);
  }

  setData(layerId: string, data: GeoJson): void {
    const src = this.map?.getSource(layerId) as
      maplibregl.GeoJSONSource | undefined;
    src?.setData(data as GeoJSON.GeoJSON);
  }

  fitBounds(bounds: BBox, padding = 40): void {
    this.map?.fitBounds(bounds, { padding, maxZoom: 18, duration: 600 });
  }

  flyTo(center: LngLat, zoom: number): void {
    this.map?.flyTo({ center, zoom, duration: 800, essential: true });
  }

  // 时相卷帘(基础实现): 以 x=0.5 为阈切换前/后图层可见性。
  // 像素级卷帘裁切(随滑块连续揭示) 将在 P1 接入 clip 实现。
  setWipe(beforeLayerId: string, afterLayerId: string, x: number): void {
    const map = this.map;
    if (!map) return;
    const showAfter = x >= 0.5;
    if (map.getLayer(beforeLayerId)) {
      map.setLayoutProperty(
        beforeLayerId,
        "visibility",
        showAfter ? "none" : "visible",
      );
    }
    if (map.getLayer(afterLayerId)) {
      map.setLayoutProperty(
        afterLayerId,
        "visibility",
        showAfter ? "visible" : "none",
      );
    }
  }

  clearWipe(): void {
    // P1: 恢复双图层可见与裁切。
  }

  on(event: MapCoreEvent, handler: MapCoreHandler): void {
    const map = this.map;
    if (!map) return;
    if (event === "moveend") map.on("moveend", () => handler(map.getBounds()));
    else if (event === "ready") map.on("load", () => handler(null));
    // featureClick / featureHover 在 P1 绑定到具体图层。
  }

  private requireMap(): maplibregl.Map {
    if (!this.map) throw new Error("MapLibreController 尚未 init()");
    return this.map;
  }
}
