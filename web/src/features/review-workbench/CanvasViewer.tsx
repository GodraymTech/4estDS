import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import type { MutableRefObject } from "react";
import maplibregl, { type MapMouseEvent } from "maplibre-gl";
import type { EffectiveAreaGeometry, ReviewCategory, ReviewItem, ReviewMapContext } from "../../shared/api";
import { basemapById, ROAD_OVERLAY } from "../../shared/map-core";
import { useReviewWorkbenchStore } from "./store";

const ITEM_SOURCE = "review-items";
const CANDIDATE_SOURCE = "review-candidates";
const REGION_SOURCE = "review-region";
const EFFECTIVE_SOURCE = "review-effective";
const TIFF_SOURCE = "review-tiff";
const BASEMAP_SOURCE = "review-basemap";
const ROAD_SOURCE = "review-road";
const INTERACTIVE_LAYERS = ["review-items-fill", "review-items-line"];

type Point = [number, number];
type Box = [number, number, number, number];

export interface ReviewMapHandle {
  zoomIn: () => void;
  zoomOut: () => void;
  fitViewport: () => void;
  resetNorth: () => void;
  getCenterPx: () => Point | null;
  setBasemap: (id: string) => void;
  setRoadOverlay: (visible: boolean) => void;
}

interface CanvasViewerProps {
  mapContext: ReviewMapContext;
  tileUrl: string;
  items: ReviewItem[];
  candidateItems?: ReviewItem[];
  categories: ReviewCategory[];
  effectiveAreaVisible: boolean;
  onSelect: (id: string, additive?: boolean) => void;
  onSelectMany: (ids: string[]) => void;
  onAddBox: (boxPx: number[]) => void;
  onUpdateBox: (id: string, boxPx: number[]) => void;
  onViewChange?: (centerPx: Point, zoom: number) => void;
}

export const CanvasViewer = forwardRef<ReviewMapHandle, CanvasViewerProps>(function CanvasViewer(
  {
    mapContext,
    tileUrl,
    items,
    candidateItems = [],
    categories,
    effectiveAreaVisible,
    onSelect,
    onSelectMany,
    onAddBox,
    onUpdateBox,
    onViewChange,
  },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const handleMarkersRef = useRef<maplibregl.Marker[]>([]);
  const dragStartRef = useRef<{ point: maplibregl.Point; lngLat: Point } | null>(null);
  const spacePanRef = useRef(false);
  const [dragBox, setDragBox] = useState<{ left: number; top: number; width: number; height: number } | null>(null);
  const [ready, setReady] = useState(false);
  const [viewEpoch, setViewEpoch] = useState(0);

  const activeTool = useReviewWorkbenchStore((state) => state.activeTool);
  const selectedIds = useReviewWorkbenchStore((state) => state.selectedIds);
  const activeId = useReviewWorkbenchStore((state) => state.activeId);
  const hiddenCategories = useReviewWorkbenchStore((state) => state.hiddenCategories);
  const regionSidePx = useReviewWorkbenchStore((state) => state.regionSidePx);
  const regionMetricsVisible = useReviewWorkbenchStore((state) => state.regionMetricsVisible);
  const setZoom = useReviewWorkbenchStore((state) => state.setZoom);

  const categoryColors = useMemo(() => {
    const colors = new Map<string, string>();
    for (const category of categories) {
      colors.set(category.id, category.color);
      colors.set(category.display_name, category.color);
    }
    return colors;
  }, [categories]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const initialBasemap = basemapById("satellite");
    const style: maplibregl.StyleSpecification = {
      version: 8,
      sources: {
        [BASEMAP_SOURCE]: {
          type: "raster",
          tiles: initialBasemap.tiles,
          tileSize: initialBasemap.tileSize ?? 256,
          attribution: initialBasemap.attribution ?? "",
        },
        [TIFF_SOURCE]: { type: "raster", tiles: [tileUrl], tileSize: 256, minzoom: 0, maxzoom: 24 },
      },
      layers: [
        { id: "review-basemap", type: "raster", source: BASEMAP_SOURCE, paint: { "raster-opacity": 0.36 } },
        { id: "review-tiff", type: "raster", source: TIFF_SOURCE, paint: { "raster-opacity": 1 } },
      ],
    };
    const [west, south, east, north] = mapContext.bounds_wgs84;
    const map = new maplibregl.Map({
      container,
      style,
      center: [(west + east) / 2, (south + north) / 2],
      zoom: 15,
      maxZoom: 24,
      attributionControl: false,
      boxZoom: false,
      pitchWithRotate: false,
    });
    mapRef.current = map;
    map.on("load", () => {
      addReviewLayers(map, mapContext.effective_geometry);
      map.fitBounds([[west, south], [east, north]], { padding: 56, maxZoom: 20, duration: 0 });
      setReady(true);
      setViewEpoch((value) => value + 1);
    });
    const reportView = () => {
      const center = lngLatToPixel([map.getCenter().lng, map.getCenter().lat], mapContext);
      const zoom = map.getZoom();
      setZoom(zoom);
      onViewChange?.(center, zoom);
      setViewEpoch((value) => value + 1);
    };
    map.on("move", reportView);
    map.on("zoom", reportView);
    return () => {
      clearMarkers(handleMarkersRef);
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
  }, [mapContext.phase_id, mapContext.tiff_id, tileUrl]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    setSourceData(map, ITEM_SOURCE, itemCollection(items, categoryColors, mapContext));
    setSourceData(map, CANDIDATE_SOURCE, itemCollection(candidateItems, categoryColors, mapContext, true));
    const visible = hiddenCategories.length
      ? (["!", ["in", ["get", "species"], ["literal", hiddenCategories]]] as maplibregl.FilterSpecification)
      : null;
    for (const layer of ["review-items-fill", "review-items-line", "review-candidates-fill", "review-candidates-line"]) {
      if (map.getLayer(layer)) map.setFilter(layer, visible);
    }
    if (map.getLayer("review-items-selected")) {
      map.setFilter("review-items-selected", visible
        ? (["all", visible, ["==", ["get", "selected"], true]] as maplibregl.FilterSpecification)
        : ["==", ["get", "selected"], true]);
    }
  }, [ready, items, candidateItems, categoryColors, hiddenCategories, mapContext]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    if (map.getLayer("review-effective-fill")) {
      map.setLayoutProperty("review-effective-fill", "visibility", effectiveAreaVisible ? "visible" : "none");
      map.setLayoutProperty("review-effective-line", "visibility", effectiveAreaVisible ? "visible" : "none");
    }
  }, [ready, effectiveAreaVisible]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const selected = new Set(selectedIds);
    const source = map.getSource(ITEM_SOURCE) as maplibregl.GeoJSONSource | undefined;
    source?.setData(itemCollection(items.map((item) => ({ ...item, __selected: selected.has(item.id) })), categoryColors, mapContext) as GeoJSON.FeatureCollection);
  }, [ready, selectedIds, items, categoryColors, mapContext]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const updateRegion = () => {
      const centerPx = lngLatToPixel([map.getCenter().lng, map.getCenter().lat], mapContext);
      const geometry = pixelBoxPolygon(
        [
          centerPx[0] - regionSidePx / 2,
          centerPx[1] - regionSidePx / 2,
          centerPx[0] + regionSidePx / 2,
          centerPx[1] + regionSidePx / 2,
        ],
        mapContext,
      );
      setSourceData(map, REGION_SOURCE, {
        type: "FeatureCollection",
        features: [{ type: "Feature", properties: {}, geometry }],
      });
    };
    updateRegion();
    if (map.getLayer("review-region-line")) {
      map.setLayoutProperty("review-region-line", "visibility", regionMetricsVisible ? "visible" : "none");
    }
  }, [ready, regionSidePx, regionMetricsVisible, viewEpoch, mapContext]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const allowPan = activeTool === "pan" || activeTool === "ai_text" || activeTool === "ai_visual";
    if (allowPan) map.dragPan.enable();
    else map.dragPan.disable();
    map.getCanvas().style.cursor = allowPan ? "grab" : activeTool === "draw" ? "crosshair" : "default";

    const mouseDown = (event: MapMouseEvent) => {
      if (event.originalEvent.button !== 0 || spacePanRef.current || !["select", "draw"].includes(activeTool)) return;
      dragStartRef.current = { point: event.point, lngLat: [event.lngLat.lng, event.lngLat.lat] };
      event.preventDefault();
    };
    const mouseMove = (event: MapMouseEvent) => {
      const start = dragStartRef.current;
      if (!start) return;
      setDragBox(rectFromPoints(start.point, event.point));
    };
    const mouseUp = (event: MapMouseEvent) => {
      const start = dragStartRef.current;
      dragStartRef.current = null;
      setDragBox(null);
      if (!start) return;
      const distance = Math.hypot(event.point.x - start.point.x, event.point.y - start.point.y);
      if (activeTool === "draw") {
        if (distance < 5) return;
        const first = lngLatToPixel(start.lngLat, mapContext);
        const second = lngLatToPixel([event.lngLat.lng, event.lngLat.lat], mapContext);
        const box = clampBox([Math.min(first[0], second[0]), Math.min(first[1], second[1]), Math.max(first[0], second[0]), Math.max(first[1], second[1])], mapContext);
        if (box[2] - box[0] >= 4 && box[3] - box[1] >= 4) onAddBox(box);
        return;
      }
      if (distance >= 5) {
        const features = map.queryRenderedFeatures([start.point, event.point], { layers: INTERACTIVE_LAYERS });
        onSelectMany([...new Set(features.map((feature) => String(feature.properties?.id ?? "")).filter(Boolean))]);
        return;
      }
      const feature = map.queryRenderedFeatures(event.point, { layers: INTERACTIVE_LAYERS })[0];
      if (feature?.properties?.id) onSelect(String(feature.properties.id), event.originalEvent.ctrlKey || event.originalEvent.metaKey);
      else onSelectMany([]);
    };
    map.on("mousedown", mouseDown);
    map.on("mousemove", mouseMove);
    map.on("mouseup", mouseUp);
    const keyDown = (event: KeyboardEvent) => {
      if (event.code !== "Space" || event.repeat || allowPan) return;
      spacePanRef.current = true;
      map.dragPan.enable();
      map.getCanvas().style.cursor = "grab";
    };
    const keyUp = (event: KeyboardEvent) => {
      if (event.code !== "Space" || allowPan) return;
      spacePanRef.current = false;
      map.dragPan.disable();
      map.getCanvas().style.cursor = activeTool === "draw" ? "crosshair" : "default";
    };
    window.addEventListener("keydown", keyDown);
    window.addEventListener("keyup", keyUp);
    return () => {
      map.off("mousedown", mouseDown);
      map.off("mousemove", mouseMove);
      map.off("mouseup", mouseUp);
      window.removeEventListener("keydown", keyDown);
      window.removeEventListener("keyup", keyUp);
      dragStartRef.current = null;
      spacePanRef.current = false;
    };
  }, [ready, activeTool, mapContext, onAddBox, onSelect, onSelectMany]);

  useEffect(() => {
    const map = mapRef.current;
    clearMarkers(handleMarkersRef);
    if (!map || !ready || activeTool !== "select") return;
    const item = items.find((value) => value.id === activeId);
    if (!item || item.frozen || !item.box_px || item.box_px.length !== 4) return;
    const original = item.box_px.map(Number) as Box;
    const points = handlePoints(original);
    handleMarkersRef.current = points.map(({ key, point }) => {
      const element = document.createElement("button");
      element.type = "button";
      element.className = "review-map-handle";
      element.setAttribute("aria-label", `调整检测框 ${key}`);
      const marker = new maplibregl.Marker({ element, draggable: true, anchor: "center" })
        .setLngLat(pixelToLngLat(point, mapContext))
        .addTo(map);
      marker.on("dragend", () => {
        const location = marker.getLngLat();
        const moved = lngLatToPixel([location.lng, location.lat], mapContext);
        onUpdateBox(item.id, resizeBox(original, key, moved, mapContext));
      });
      return marker;
    });
    return () => clearMarkers(handleMarkersRef);
  }, [ready, activeTool, activeId, items, mapContext, onUpdateBox]);

  useImperativeHandle(ref, () => ({
    zoomIn: () => mapRef.current?.zoomIn({ duration: 180 }),
    zoomOut: () => mapRef.current?.zoomOut({ duration: 180 }),
    fitViewport: () => {
      const [west, south, east, north] = mapContext.bounds_wgs84;
      mapRef.current?.fitBounds([[west, south], [east, north]], { padding: 56, maxZoom: 20 });
    },
    resetNorth: () => mapRef.current?.resetNorth({ duration: 240 }),
    getCenterPx: () => {
      const center = mapRef.current?.getCenter();
      return center ? lngLatToPixel([center.lng, center.lat], mapContext) : null;
    },
    setBasemap: (id) => {
      const source = mapRef.current?.getSource(BASEMAP_SOURCE) as maplibregl.RasterTileSource | undefined;
      source?.setTiles(basemapById(id).tiles);
    },
    setRoadOverlay: (visible) => setRoadOverlay(mapRef.current, visible),
  }), [mapContext]);

  const centerPx = mapRef.current
    ? lngLatToPixel([mapRef.current.getCenter().lng, mapRef.current.getCenter().lat], mapContext)
    : ([mapContext.pixel_width / 2, mapContext.pixel_height / 2] as Point);
  const actualRegion = clampBox([
    centerPx[0] - regionSidePx / 2,
    centerPx[1] - regionSidePx / 2,
    centerPx[0] + regionSidePx / 2,
    centerPx[1] + regionSidePx / 2,
  ], mapContext);

  return (
    <div className="review-map-shell">
      <div ref={containerRef} className="review-map" />
      {dragBox ? <div className={`review-drag-box review-drag-box--${activeTool}`} style={dragBox} /> : null}
      {regionMetricsVisible ? (
        <div className="review-region-metric" aria-live="polite">
          <strong>{Math.round(actualRegion[2] - actualRegion[0])} × {Math.round(actualRegion[3] - actualRegion[1])} px</strong>
          <span>{((actualRegion[2] - actualRegion[0]) * mapContext.gsd).toFixed(1)} × {((actualRegion[3] - actualRegion[1]) * mapContext.gsd).toFixed(1)} m</span>
        </div>
      ) : null}
    </div>
  );
});

function addReviewLayers(map: maplibregl.Map, effectiveGeometry?: EffectiveAreaGeometry | null) {
  map.addSource(EFFECTIVE_SOURCE, { type: "geojson", data: featureCollection(effectiveGeometry) });
  map.addLayer({ id: "review-effective-fill", type: "fill", source: EFFECTIVE_SOURCE, layout: { visibility: "none" }, paint: { "fill-color": "#46a171", "fill-opacity": 0.07 } });
  map.addLayer({ id: "review-effective-line", type: "line", source: EFFECTIVE_SOURCE, layout: { visibility: "none" }, paint: { "line-color": "#d9fff0", "line-width": 2, "line-dasharray": [3, 2] } });
  map.addSource(REGION_SOURCE, { type: "geojson", data: featureCollection() });
  map.addLayer({ id: "review-region-line", type: "line", source: REGION_SOURCE, layout: { visibility: "none" }, paint: { "line-color": "#f0c96a", "line-width": 1.5, "line-opacity": 0.9, "line-dasharray": [3, 2] } });
  map.addSource(ITEM_SOURCE, { type: "geojson", data: featureCollection() });
  map.addLayer({ id: "review-items-fill", type: "fill", source: ITEM_SOURCE, paint: { "fill-color": ["get", "color"], "fill-opacity": ["case", ["boolean", ["get", "frozen"], false], 0, ["boolean", ["get", "selected"], false], 0.2, 0.1] } });
  map.addLayer({ id: "review-items-line", type: "line", source: ITEM_SOURCE, paint: { "line-color": ["get", "color"], "line-width": ["case", ["boolean", ["get", "selected"], false], 3, 1.5], "line-opacity": ["case", ["boolean", ["get", "frozen"], false], 0.62, 0.95], "line-dasharray": ["case", ["==", ["get", "status"], "pending"], [2, 2], [1, 0]] } });
  map.addLayer({ id: "review-items-selected", type: "line", source: ITEM_SOURCE, filter: ["==", ["get", "selected"], true], paint: { "line-color": "#ffffff", "line-width": 1, "line-offset": 3, "line-opacity": 0.86 } });
  map.addSource(CANDIDATE_SOURCE, { type: "geojson", data: featureCollection() });
  map.addLayer({ id: "review-candidates-fill", type: "fill", source: CANDIDATE_SOURCE, paint: { "fill-color": ["get", "color"], "fill-opacity": 0.18 } });
  map.addLayer({ id: "review-candidates-line", type: "line", source: CANDIDATE_SOURCE, paint: { "line-color": ["get", "color"], "line-width": 2, "line-dasharray": [2, 1.5] } });
}

function itemCollection(items: ReviewItem[], colors: Map<string, string>, context: ReviewMapContext, candidate = false): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: items.flatMap((item): GeoJSON.Feature[] => {
      const box = item.box_wgs84;
      const pixelBox = item.box_px?.length === 4 ? item.box_px.map(Number) as Box : null;
      if ((!box || box.length !== 4) && !pixelBox) return [];
      const geometry = (candidate || (item.source === "ai" && !item.frozen)) && pixelBox
        ? ellipsePolygon(pixelBox, context)
        : box && box.length === 4
          ? geographicBoxPolygon(box.map(Number) as Box)
          : pixelBoxPolygon(pixelBox as Box, context);
      return [{
        type: "Feature",
        properties: {
          id: item.id,
          species: item.species,
          status: item.status,
          frozen: Boolean(item.frozen),
          selected: Boolean((item as ReviewItem & { __selected?: boolean }).__selected),
          candidate,
          color: colors.get(item.species) ?? "#72bc8f",
        },
        geometry,
      }];
    }),
  };
}

function featureCollection(geometry?: EffectiveAreaGeometry | null): GeoJSON.FeatureCollection {
  return { type: "FeatureCollection", features: geometry ? [{ type: "Feature", properties: {}, geometry: geometry as GeoJSON.Polygon | GeoJSON.MultiPolygon }] : [] };
}

function setSourceData(map: maplibregl.Map, id: string, data: GeoJSON.FeatureCollection) {
  (map.getSource(id) as maplibregl.GeoJSONSource | undefined)?.setData(data);
}

function pixelToLngLat([x, y]: Point, context: ReviewMapContext): Point {
  const u = Math.max(0, Math.min(1, x / Math.max(1, context.pixel_width)));
  const v = Math.max(0, Math.min(1, y / Math.max(1, context.pixel_height)));
  const [tl, tr, br, bl] = context.corner_wgs84;
  const top: Point = [tl[0] + (tr[0] - tl[0]) * u, tl[1] + (tr[1] - tl[1]) * u];
  const bottom: Point = [bl[0] + (br[0] - bl[0]) * u, bl[1] + (br[1] - bl[1]) * u];
  return [top[0] + (bottom[0] - top[0]) * v, top[1] + (bottom[1] - top[1]) * v];
}

function lngLatToPixel(target: Point, context: ReviewMapContext): Point {
  const [west, south, east, north] = context.bounds_wgs84;
  let u = (target[0] - west) / Math.max(1e-12, east - west);
  let v = (north - target[1]) / Math.max(1e-12, north - south);
  for (let index = 0; index < 8; index += 1) {
    const value = pixelToLngLat([u * context.pixel_width, v * context.pixel_height], context);
    const epsilon = 1e-5;
    const du = pixelToLngLat([(u + epsilon) * context.pixel_width, v * context.pixel_height], context);
    const dv = pixelToLngLat([u * context.pixel_width, (v + epsilon) * context.pixel_height], context);
    const a = (du[0] - value[0]) / epsilon;
    const b = (dv[0] - value[0]) / epsilon;
    const c = (du[1] - value[1]) / epsilon;
    const d = (dv[1] - value[1]) / epsilon;
    const determinant = a * d - b * c;
    if (Math.abs(determinant) < 1e-16) break;
    const errorX = target[0] - value[0];
    const errorY = target[1] - value[1];
    u += (errorX * d - b * errorY) / determinant;
    v += (a * errorY - errorX * c) / determinant;
  }
  return [Math.max(0, Math.min(context.pixel_width, u * context.pixel_width)), Math.max(0, Math.min(context.pixel_height, v * context.pixel_height))];
}

function pixelBoxPolygon(box: number[], context: ReviewMapContext): GeoJSON.Polygon {
  const clamped = clampBox(box as Box, context);
  const corners = [
    pixelToLngLat([clamped[0], clamped[1]], context),
    pixelToLngLat([clamped[2], clamped[1]], context),
    pixelToLngLat([clamped[2], clamped[3]], context),
    pixelToLngLat([clamped[0], clamped[3]], context),
  ];
  return { type: "Polygon", coordinates: [[...corners, corners[0]]] };
}

function geographicBoxPolygon([west, south, east, north]: Box): GeoJSON.Polygon {
  return { type: "Polygon", coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]] };
}

function ellipsePolygon(box: Box, context: ReviewMapContext): GeoJSON.Polygon {
  const [x1, y1, x2, y2] = clampBox(box, context);
  const centerX = (x1 + x2) / 2;
  const centerY = (y1 + y2) / 2;
  const radiusX = (x2 - x1) / 2;
  const radiusY = (y2 - y1) / 2;
  const ring: Point[] = [];
  for (let index = 0; index <= 32; index += 1) {
    const angle = index / 32 * Math.PI * 2;
    ring.push(pixelToLngLat([centerX + Math.cos(angle) * radiusX, centerY + Math.sin(angle) * radiusY], context));
  }
  return { type: "Polygon", coordinates: [ring] };
}

function clampBox(box: Box, context: ReviewMapContext): Box {
  return [
    Math.max(0, Math.min(context.pixel_width - 1, box[0])),
    Math.max(0, Math.min(context.pixel_height - 1, box[1])),
    Math.max(1, Math.min(context.pixel_width, box[2])),
    Math.max(1, Math.min(context.pixel_height, box[3])),
  ];
}

function handlePoints([x1, y1, x2, y2]: Box): Array<{ key: string; point: Point }> {
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  return [
    { key: "nw", point: [x1, y1] }, { key: "n", point: [mx, y1] }, { key: "ne", point: [x2, y1] },
    { key: "e", point: [x2, my] }, { key: "se", point: [x2, y2] }, { key: "s", point: [mx, y2] },
    { key: "sw", point: [x1, y2] }, { key: "w", point: [x1, my] },
  ];
}

function resizeBox(original: Box, handle: string, point: Point, context: ReviewMapContext): Box {
  let [x1, y1, x2, y2] = original;
  if (handle.includes("w")) x1 = Math.min(x2 - 4, point[0]);
  if (handle.includes("e")) x2 = Math.max(x1 + 4, point[0]);
  if (handle.includes("n")) y1 = Math.min(y2 - 4, point[1]);
  if (handle.includes("s")) y2 = Math.max(y1 + 4, point[1]);
  return clampBox([x1, y1, x2, y2], context);
}

function rectFromPoints(first: maplibregl.Point, second: maplibregl.Point) {
  return { left: Math.min(first.x, second.x), top: Math.min(first.y, second.y), width: Math.abs(first.x - second.x), height: Math.abs(first.y - second.y) };
}

function clearMarkers(ref: MutableRefObject<maplibregl.Marker[]>) {
  for (const marker of ref.current) marker.remove();
  ref.current = [];
}

function setRoadOverlay(map: maplibregl.Map | null, visible: boolean) {
  if (!map) return;
  if (!visible) {
    if (map.getLayer("review-road")) map.removeLayer("review-road");
    if (map.getSource(ROAD_SOURCE)) map.removeSource(ROAD_SOURCE);
    return;
  }
  if (!map.getSource(ROAD_SOURCE)) map.addSource(ROAD_SOURCE, { type: "raster", tiles: ROAD_OVERLAY.tiles, tileSize: ROAD_OVERLAY.tileSize ?? 256 });
  if (!map.getLayer("review-road")) map.addLayer(
    { id: "review-road", type: "raster", source: ROAD_SOURCE, paint: { "raster-opacity": 0.22 } },
    map.getLayer("review-effective-fill") ? "review-effective-fill" : undefined,
  );
}
