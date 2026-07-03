import maplibregl from "maplibre-gl";
import type {
  BBox,
  Camera,
  GeoJson,
  GeoJsonLayerSpec,
  LngLat,
  MapCoreEvent,
  MapCoreHandler,
  MapInitOptions,
  MarkerSpec,
} from "./types";
import type { MapController } from "./MapController";

const DEFAULT_POINT_COLOR = "#0e6e63";
const DEFAULT_POLYGON_COLOR = "#3e8e5a";

/**
 * MapController 的 MapLibre 实现。
 * 所有 maplibre-gl 的依赖被封闭在本文件内; 业务层只面向 MapController 接口。
 */
export class MapLibreController implements MapController {
  private map: maplibregl.Map | null = null;
  private ready = false;
  private markers = new Map<string, maplibregl.Marker>();

  private rasterStyle(
    basemap: MapInitOptions["basemap"],
  ): maplibregl.StyleSpecification {
    return {
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
    };
  }

  init(opts: MapInitOptions): Promise<void> {
    const interactive = opts.interactive ?? true;
    return new Promise((resolve) => {
      const map = new maplibregl.Map({
        container: opts.container,
        style: this.rasterStyle(opts.basemap),
        center: opts.center,
        zoom: opts.zoom,
        interactive,
        attributionControl: false,
      });
      if (interactive)
        map.addControl(new maplibregl.NavigationControl({}), "top-right");
      map.on("load", () => {
        this.ready = true;
        resolve();
      });
      this.map = map;
    });
  }

  destroy(): void {
    this.clearMarkers();
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
          "fill-opacity": 0.3,
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

  setMarkers(markers: MarkerSpec[]): void {
    const map = this.requireMap();
    this.clearMarkers();
    for (const m of markers) {
      const marker = new maplibregl.Marker({
        element: m.element,
        anchor: "bottom",
      })
        .setLngLat(m.lngLat)
        .addTo(map);
      this.markers.set(m.id, marker);
    }
  }

  clearMarkers(): void {
    for (const marker of this.markers.values()) marker.remove();
    this.markers.clear();
  }

  fitBounds(bounds: BBox, padding = 40): void {
    this.map?.fitBounds(bounds, { padding, maxZoom: 18, duration: 600 });
  }

  flyTo(center: LngLat, zoom: number): void {
    this.map?.flyTo({ center, zoom, duration: 800, essential: true });
  }

  getCamera(): Camera {
    const map = this.requireMap();
    const c = map.getCenter();
    return {
      center: [c.lng, c.lat],
      zoom: map.getZoom(),
      bearing: map.getBearing(),
      pitch: map.getPitch(),
    };
  }

  jumpTo(camera: Camera): void {
    this.map?.jumpTo({
      center: camera.center,
      zoom: camera.zoom,
      bearing: camera.bearing,
      pitch: camera.pitch,
    });
  }

  on(event: MapCoreEvent, handler: MapCoreHandler): void {
    const map = this.map;
    if (!map) return;
    if (event === "move") map.on("move", () => handler(null));
    else if (event === "moveend")
      map.on("moveend", () => handler(map.getBounds()));
    else if (event === "ready") map.on("load", () => handler(null));
    // featureClick / featureHover 在后续绑定到具体图层。
  }

  private requireMap(): maplibregl.Map {
    if (!this.map) throw new Error("MapLibreController 尚未 init()");
    return this.map;
  }
}
