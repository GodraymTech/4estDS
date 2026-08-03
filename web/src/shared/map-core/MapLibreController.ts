import maplibregl from "maplibre-gl";
import { env } from "../config/env";
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
import type { MapController } from "./MapController";

const DEFAULT_POINT_COLOR = "#0e6e63";
const DEFAULT_POLYGON_COLOR = "#3e8e5a";
const DEFAULT_LINE_COLOR = "#b8472a";

function toMapLibreGeoJson(data: GeoJson): GeoJSON.GeoJSON {
  return data as unknown as GeoJSON.GeoJSON;
}

/**
 * MapController 的 MapLibre 实现。
 * 所有 maplibre-gl 的依赖被封闭在本文件内; 业务层只面向 MapController 接口。
 */
export class MapLibreController implements MapController {
  private map: maplibregl.Map | null = null;
  private ready = false;
  private markers = new Map<string, maplibregl.Marker>();
  private rasterOverlayTileKeys = new Map<string, string>();
  private basemapTileKey = "";
  private basemapSourceId = "basemap";

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
    this.basemapSourceId = opts.basemap.id;
    this.basemapTileKey = JSON.stringify({
      tiles: opts.basemap.tiles,
      tileSize: opts.basemap.tileSize ?? 256,
    });
    return new Promise((resolve) => {
      const map = new maplibregl.Map({
        container: opts.container,
        style: this.rasterStyle(opts.basemap),
        center: opts.center,
        zoom: opts.zoom,
        maxZoom: env.maxZoom,
        interactive,
        attributionControl: false,
      });
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
    this.basemapTileKey = "";
    this.rasterOverlayTileKeys.clear();
  }

  isReady(): boolean {
    return this.ready;
  }

  setGeoJsonLayer(spec: GeoJsonLayerSpec): void {
    const map = this.requireMap();
    if (!map.getSource(spec.id)) {
      map.addSource(spec.id, {
        type: "geojson",
        data: toMapLibreGeoJson(spec.data),
      });
    } else {
      this.setData(spec.id, spec.data);
    }
    if (map.getLayer(spec.id)) {
      map.moveLayer(spec.id);
      return;
    }
    if (spec.kind === "point") {
      map.addLayer({
        id: spec.id,
        type: "circle",
        source: spec.id,
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 2, 16, 6],
          "circle-color": (spec.color ?? DEFAULT_POINT_COLOR) as never,
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 0.5,
          "circle-opacity": spec.opacity ?? 0.85,
        },
      });
    } else if (spec.kind === "line") {
      const paint: Record<string, unknown> = {
        "line-color": spec.color ?? DEFAULT_LINE_COLOR,
        "line-width": spec.lineWidth ?? 2.5,
        "line-opacity": spec.opacity ?? 1,
      };
      if (spec.dashArray?.length) paint["line-dasharray"] = spec.dashArray;
      map.addLayer({
        id: spec.id,
        type: "line",
        source: spec.id,
        layout: { "line-cap": "round", "line-join": "round" },
        paint,
      });
    } else {
      map.addLayer({
        id: spec.id,
        type: "fill",
        source: spec.id,
        paint: {
          "fill-color": (spec.color ?? DEFAULT_POLYGON_COLOR) as never,
          "fill-opacity": spec.opacity ?? 0.3,
          "fill-outline-color": "#1a5c38",
        },
      });
    }
    map.moveLayer(spec.id);
  }

  removeLayer(id: string): void {
    this.rasterOverlayTileKeys.delete(id);
    const map = this.map;
    if (!map) return;
    if (map.getLayer(id)) map.removeLayer(id);
    if (map.getSource(id)) map.removeSource(id);
  }

  setData(layerId: string, data: GeoJson): void {
    const src = this.map?.getSource(layerId) as
      maplibregl.GeoJSONSource | undefined;
    src?.setData(toMapLibreGeoJson(data));
  }

  setMarkers(markers: MarkerSpec[]): void {
    const map = this.requireMap();
    this.clearMarkers();
    for (const m of markers) {
      const marker = new maplibregl.Marker({
        element: m.element,
        anchor: "bottom",
        offset: m.offset,
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

  fitBounds(bounds: BBox, options: number | FitBoundsOptions = 40): void {
    const opts = typeof options === "number" ? { padding: options } : options;
    this.map?.fitBounds(bounds, {
      padding: opts.padding ?? 40,
      maxZoom: opts.maxZoom ?? 18,
      duration: opts.duration ?? 600,
    });
  }

  flyTo(center: LngLat, zoom: number): void {
    this.map?.flyTo({ center, zoom, duration: 800, essential: true });
  }

  zoomIn(): void {
    this.map?.zoomIn({ duration: 180 });
  }

  zoomOut(): void {
    this.map?.zoomOut({ duration: 180 });
  }

  getZoom(): number {
    return this.map?.getZoom() ?? 0;
  }

  getBounds(): BBox {
    const bounds = this.requireMap().getBounds();
    return [
      [bounds.getWest(), bounds.getSouth()],
      [bounds.getEast(), bounds.getNorth()],
    ];
  }

  setMaxBounds(bounds: BBox | null): void {
    if (!this.map) return;
    if (!bounds) {
      this.map.setMaxBounds(undefined);
      return;
    }
    this.map.setMaxBounds(new maplibregl.LngLatBounds(bounds[0], bounds[1]));
  }

  setMinZoom(zoom: number | null): void {
    if (!this.map) return;
    if (zoom === null) return;
    this.map.setMinZoom(zoom);
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

  setCursor(cursor: string | null): void {
    const map = this.map;
    if (!map) return;
    map.getCanvas().style.cursor = cursor ?? "";
  }

  setBasemap(basemap: RasterBasemap): void {
    const src = this.map?.getSource(this.basemapSourceId) as
      maplibregl.RasterTileSource | undefined;
    const tileKey = JSON.stringify({
      tiles: basemap.tiles,
      tileSize: basemap.tileSize ?? 256,
    });
    if (src && typeof src.setTiles === "function" && this.basemapTileKey !== tileKey) {
      src.setTiles(basemap.tiles);
      this.basemapTileKey = tileKey;
    }
  }

  setRasterOverlay(id: string, overlay: RasterOverlaySpec): void {
    const map = this.requireMap();
    const tileKey = JSON.stringify({
      tiles: overlay.tiles,
      tileSize: overlay.tileSize ?? 256,
      minZoom: overlay.minZoom ?? null,
      maxZoom: overlay.maxZoom ?? null,
    });
    if (!map.getSource(id)) {
      const source: maplibregl.RasterSourceSpecification = {
        type: "raster",
        tiles: overlay.tiles,
        tileSize: overlay.tileSize ?? 256,
        attribution: overlay.attribution ?? "",
      };
      if (typeof overlay.minZoom === "number") source.minzoom = overlay.minZoom;
      if (typeof overlay.maxZoom === "number") source.maxzoom = overlay.maxZoom;
      map.addSource(id, {
        ...source,
        maxzoom: source.maxzoom ?? env.maxZoom,
      } as maplibregl.RasterSourceSpecification);
      this.rasterOverlayTileKeys.set(id, tileKey);
    } else {
      const src = map.getSource(id) as maplibregl.RasterTileSource;
      if (typeof src.setTiles === "function" && this.rasterOverlayTileKeys.get(id) !== tileKey) {
        src.setTiles(overlay.tiles);
        this.rasterOverlayTileKeys.set(id, tileKey);
      }
    }
    if (!map.getLayer(id)) {
      const layers = map.getStyle().layers;
      const vectorTypes = ["fill", "line", "circle", "symbol"];
      const firstVector = layers?.find((l) => l.id !== "base" && vectorTypes.includes(l.type));
      map.addLayer({
        id,
        type: "raster",
        source: id,
        paint: { "raster-opacity": overlay.opacity ?? 0.9 },
      }, firstVector?.id);
      return;
    }
    map.setPaintProperty(id, "raster-opacity", overlay.opacity ?? 0.9);
  }

  removeRasterOverlay(id: string): void {
    this.removeLayer(id);
  }

  on(event: MapCoreEvent, handler: MapCoreHandler): () => void {
    const map = this.map;
    if (!map) return () => {};
    if (event === "mapClick") {
      const cb = (e: maplibregl.MapMouseEvent) =>
        handler([e.lngLat.lng, e.lngLat.lat] as LngLat);
      map.on("click", cb);
      return () => map.off("click", cb);
    }
    if (event === "move") {
      const cb = () => handler(null);
      map.on("move", cb);
      return () => map.off("move", cb);
    }
    if (event === "moveend") {
      const cb = () => handler(map.getBounds());
      map.on("moveend", cb);
      return () => map.off("moveend", cb);
    }
    if (event === "ready") {
      const cb = () => handler(null);
      map.on("load", cb);
      return () => map.off("load", cb);
    }
    // featureClick / featureHover 在后续绑定到具体图层。
    return () => {};
  }

  private requireMap(): maplibregl.Map {
    if (!this.map) throw new Error("MapLibreController 尚未 init()");
    return this.map;
  }
}
