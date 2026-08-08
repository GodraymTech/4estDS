import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
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
  onVisualPromptBox?: (boxPx: number[]) => void;
  onUpdateBox: (id: string, boxPx: number[]) => void;
  onViewChange?: (centerPx: Point, zoom: number) => void;
}

type HandleKey = "nw" | "n" | "ne" | "e" | "se" | "s" | "sw" | "w";

const HANDLE_CURSORS: Record<HandleKey, string> = {
  nw: "nwse-resize",
  n: "ns-resize",
  ne: "nesw-resize",
  e: "ew-resize",
  se: "nwse-resize",
  s: "ns-resize",
  sw: "nesw-resize",
  w: "ew-resize",
};

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
    onVisualPromptBox,
    onUpdateBox,
    onViewChange,
  },
  ref,
) {
type ScreenBox = { left: number; top: number; width: number; height: number };

  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const spacePanRef = useRef(false);
  const [ready, setReady] = useState(false);
  const [viewEpoch, setViewEpoch] = useState(0);
  const [dragBox, setDragBox] = useState<ScreenBox | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [activeTransformBox, setActiveTransformBox] = useState<Box | null>(null);
  const [isTransforming, setIsTransforming] = useState(false);

  const activeTool = useReviewWorkbenchStore((state) => state.activeTool);
  const selectPanInverted = useReviewWorkbenchStore((state) => state.selectPanInverted);
  const selectedIds = useReviewWorkbenchStore((state) => state.selectedIds);
  const activeId = useReviewWorkbenchStore((state) => state.activeId);
  const hiddenCategories = useReviewWorkbenchStore((state) => state.hiddenCategories);
  const hiddenItemIds = useReviewWorkbenchStore((state) => state.hiddenItemIds);
  const regionSidePx = useReviewWorkbenchStore((state) => state.regionSidePx);
  const regionMetricsVisible = useReviewWorkbenchStore((state) => state.regionMetricsVisible);
  const setZoom = useReviewWorkbenchStore((state) => state.setZoom);

  // 拖拽操作引用
  const mouseOpRef = useRef<{
    type: "draw" | "visual_prompt_draw" | "marquee" | "move" | "pan" | "rotate";
    button: number;
    startScreen: Point;
    lastScreen: Point;
    startPx: Point;
    originalBox?: Box;
    targetItemId?: string;
    initialBearing?: number;
  } | null>(null);

  const categoryColors = useMemo(() => {
    const colors = new Map<string, string>();
    for (const category of categories) {
      colors.set(category.id, category.color);
      colors.set(category.display_name, category.color);
    }
    return colors;
  }, [categories]);

  // 获取当前选中的激活对象
  const activeItem = useMemo(() => {
    return items.find((item) => item.id === activeId && !item.frozen && item.box_px?.length === 4) ?? null;
  }, [items, activeId]);

  // 地图初始化
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
      dragPan: false, // 由交互逻辑精细控制左/右键与平移
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

    // 禁用默认右键菜单，保障右键平移/框选的顺畅体验
    const onContextMenu = (event: MouseEvent) => {
      event.preventDefault();
    };
    container.addEventListener("contextmenu", onContextMenu);

    return () => {
      container.removeEventListener("contextmenu", onContextMenu);
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
  }, [mapContext.phase_id, mapContext.tiff_id, tileUrl]);

  // 更新 GeoJSON 数据源与样式过滤（高对比度纯线框渲染）
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const selectedSet = new Set(selectedIds);
    const renderedItems = items.filter((item) => !hiddenItemIds.includes(item.id));
    setSourceData(
      map,
      ITEM_SOURCE,
      itemCollection(
        renderedItems.map((item) => ({
          ...item,
          __selected: selectedSet.has(item.id),
          __hovered: item.id === hoveredId,
        })),
        categoryColors,
        mapContext,
      ),
    );
    setSourceData(map, CANDIDATE_SOURCE, itemCollection(candidateItems, categoryColors, mapContext, true));

    const visible = hiddenCategories.length
      ? (["!", ["in", ["get", "species"], ["literal", hiddenCategories]]] as maplibregl.FilterSpecification)
      : null;
    for (const layer of ["review-items-fill", "review-items-line", "review-candidates-fill", "review-candidates-line"]) {
      if (map.getLayer(layer)) map.setFilter(layer, visible);
    }
    if (map.getLayer("review-items-selected")) {
      map.setFilter(
        "review-items-selected",
        visible
          ? (["all", visible, ["==", ["get", "selected"], true]] as maplibregl.FilterSpecification)
          : ["==", ["get", "selected"], true],
      );
    }
  }, [ready, items, candidateItems, categoryColors, hiddenCategories, hiddenItemIds, selectedIds, hoveredId, mapContext]);

  // 有效区域图层可见性
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    if (map.getLayer("review-effective-fill")) {
      map.setLayoutProperty("review-effective-fill", "visibility", effectiveAreaVisible ? "visible" : "none");
      map.setLayoutProperty("review-effective-line", "visibility", effectiveAreaVisible ? "visible" : "none");
    }
  }, [ready, effectiveAreaVisible]);

  // AI 范围指示框
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

  // 几何级 Hit-Testing 判定
  const findItemAtPx = useCallback(
    (pointPx: Point, tolerancePx = 6): ReviewItem | null => {
      const [px, py] = pointPx;
      const visible = items.filter((item) => !hiddenCategories.includes(item.species) && !hiddenItemIds.includes(item.id) && item.box_px?.length === 4);
      const sorted = [...visible].sort((a, b) => {
        const aSel = selectedIds.includes(a.id);
        const bSel = selectedIds.includes(b.id);
        if (aSel && !bSel) return -1;
        if (!aSel && bSel) return 1;
        const aArea = (a.box_px![2] - a.box_px![0]) * (a.box_px![3] - a.box_px![1]);
        const bArea = (b.box_px![2] - b.box_px![0]) * (b.box_px![3] - b.box_px![1]);
        return aArea - bArea;
      });

      for (const item of sorted) {
        const [x1, y1, x2, y2] = item.box_px!;
        if (
          px >= Math.min(x1, x2) - tolerancePx &&
          px <= Math.max(x1, x2) + tolerancePx &&
          py >= Math.min(y1, y2) - tolerancePx &&
          py <= Math.max(y1, y2) + tolerancePx
        ) {
          return item;
        }
      }
      return null;
    },
    [items, hiddenCategories, hiddenItemIds, selectedIds],
  );

  // 视口与屏幕坐标系下的鼠标事件控制
  // 核心逻辑:
  // 1. 默认模式 (!selectPanInverted):
  //    左键 (button 0): 点选/框选/框平移;
  //    右键 (button 2): 平移地图 (Pan Map);
  // 2. 反转模式 (selectPanInverted):
  //    左键 (button 0): 平移地图 (Pan Map);
  //    右键 (button 2): 点选/框选/框平移;
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;

    // 鼠标移动与 Hover
    const onMouseMove = (event: MapMouseEvent) => {
      const op = mouseOpRef.current;
      const currentScreen: Point = [event.point.x, event.point.y];

      if (op) {
        if (op.type === "rotate" && op.initialBearing !== undefined) {
          const dx = currentScreen[0] - op.startScreen[0];
          const newBearing = op.initialBearing + dx * 0.45;
          map.setBearing(newBearing);
          map.getCanvas().style.cursor = "grabbing";
          return;
        }

        if (op.type === "pan") {
          const dx = currentScreen[0] - op.lastScreen[0];
          const dy = currentScreen[1] - op.lastScreen[1];
          op.lastScreen = currentScreen;
          map.panBy([-dx, -dy], { duration: 0 });
          map.getCanvas().style.cursor = "grabbing";
          return;
        }

        const currentPx = lngLatToPixel([event.lngLat.lng, event.lngLat.lat], mapContext);

        if (op.type === "draw" || op.type === "visual_prompt_draw" || op.type === "marquee") {
          setDragBox({
            left: Math.min(op.startScreen[0], currentScreen[0]),
            top: Math.min(op.startScreen[1], currentScreen[1]),
            width: Math.abs(currentScreen[0] - op.startScreen[0]),
            height: Math.abs(currentScreen[1] - op.startScreen[1]),
          });
        } else if (op.type === "move" && op.originalBox && op.targetItemId) {
          const dx = currentPx[0] - op.startPx[0];
          const dy = currentPx[1] - op.startPx[1];
          const newBox = clampBox(
            [
              op.originalBox[0] + dx,
              op.originalBox[1] + dy,
              op.originalBox[2] + dx,
              op.originalBox[3] + dy,
            ],
            mapContext,
          );
          setActiveTransformBox(newBox);
        }
        return;
      }

      // 未拖拽时的 Hover 与光标状态自适应
      if (spacePanRef.current) {
        map.getCanvas().style.cursor = "grab";
        return;
      }

      if (activeTool === "draw") {
        map.getCanvas().style.cursor = "crosshair";
        return;
      }

      if (activeTool === "ai_visual") {
        const currentPx = lngLatToPixel([event.lngLat.lng, event.lngLat.lat], mapContext);
        const hit = findItemAtPx(currentPx);
        setHoveredId(hit ? hit.id : null);
        map.getCanvas().style.cursor = hit ? "pointer" : "crosshair";
        return;
      }

      if (activeTool === "ai_text") {
        map.getCanvas().style.cursor = "grab";
        return;
      }

      if (activeTool === "select") {
        const currentPx = lngLatToPixel([event.lngLat.lng, event.lngLat.lat], mapContext);
        const hit = findItemAtPx(currentPx);
        setHoveredId(hit ? hit.id : null);

        if (selectPanInverted) {
          // 反转模式下左键是平移地图
          if (hit) {
            map.getCanvas().style.cursor = selectedIds.includes(hit.id) && !hit.frozen ? "move" : "pointer";
          } else {
            map.getCanvas().style.cursor = "grab";
          }
        } else {
          // 默认模式下左键是选择/框选
          if (hit) {
            map.getCanvas().style.cursor = selectedIds.includes(hit.id) && !hit.frozen ? "move" : "pointer";
          } else {
            map.getCanvas().style.cursor = "default";
          }
        }
      }
    };

    // 鼠标按下
    const onMouseDown = (event: MapMouseEvent) => {
      if (isTransforming) return;
      const button = event.originalEvent.button; // 0 为左键, 1 为中键, 2 为右键
      if (button !== 0 && button !== 1 && button !== 2) return;

      const screenPt: Point = [event.point.x, event.point.y];
      const pointPx = lngLatToPixel([event.lngLat.lng, event.lngLat.lat], mapContext);

      // 鼠标中键 (button 1): 按住拖拽旋转地图
      if (button === 1) {
        mouseOpRef.current = {
          type: "rotate",
          button,
          startScreen: screenPt,
          lastScreen: screenPt,
          startPx: pointPx,
          initialBearing: map.getBearing(),
        };
        map.getCanvas().style.cursor = "grabbing";
        event.preventDefault();
        return;
      }

      // 空格漫游，或文本 Prompt 工具下的自由平移
      if (spacePanRef.current || activeTool === "ai_text") {
        mouseOpRef.current = {
          type: "pan",
          button,
          startScreen: screenPt,
          lastScreen: screenPt,
          startPx: pointPx,
        };
        map.getCanvas().style.cursor = "grabbing";
        event.preventDefault();
        return;
      }

      const isDrawAction = (activeTool as string) === "draw" || (activeTool as string) === "ai_visual";
      if (isDrawAction) {
        if (button === 0) {
          const hit = (activeTool as string) === "ai_visual" ? findItemAtPx(pointPx) : null;
          mouseOpRef.current = {
            type: (activeTool as string) === "ai_visual" ? "visual_prompt_draw" : "draw",
            button,
            startScreen: screenPt,
            lastScreen: screenPt,
            startPx: pointPx,
            targetItemId: hit ? hit.id : undefined,
          };
          event.preventDefault();
        } else if (button === 2) {
          // 画框或视觉样例模式下右键可随时平移地图
          mouseOpRef.current = {
            type: "pan",
            button,
            startScreen: screenPt,
            lastScreen: screenPt,
            startPx: pointPx,
          };
          map.getCanvas().style.cursor = "grabbing";
          event.preventDefault();
        }
        return;
      }

      if (activeTool === "select") {
        const isSelectAction = (!selectPanInverted && button === 0) || (selectPanInverted && button === 2);
        const isPanAction = (!selectPanInverted && button === 2) || (selectPanInverted && button === 0);

        if (isPanAction) {
          mouseOpRef.current = {
            type: "pan",
            button,
            startScreen: screenPt,
            lastScreen: screenPt,
            startPx: pointPx,
          };
          map.getCanvas().style.cursor = "grabbing";
          event.preventDefault();
          return;
        }

        if (isSelectAction) {
          const hit = findItemAtPx(pointPx);
          if (hit) {
            const isSelected = selectedIds.includes(hit.id);
            const isAdditive = event.originalEvent.ctrlKey || event.originalEvent.metaKey || event.originalEvent.shiftKey;
            if (!isSelected || isAdditive) {
              onSelect(hit.id, isAdditive);
            }
            if (!hit.frozen && hit.box_px?.length === 4 && !isAdditive) {
              mouseOpRef.current = {
                type: "move",
                button,
                startScreen: screenPt,
                lastScreen: screenPt,
                startPx: pointPx,
                originalBox: [...hit.box_px] as Box,
                targetItemId: hit.id,
              };
            }
          } else {
            // 点击了空白处，进入框选模式
            mouseOpRef.current = {
              type: "marquee",
              button,
              startScreen: screenPt,
              lastScreen: screenPt,
              startPx: pointPx,
            };
          }
          event.preventDefault();
        }
      }
    };

    // 鼠标抬起
    const onMouseUp = (event: MapMouseEvent) => {
      const op = mouseOpRef.current;
      mouseOpRef.current = null;
      setDragBox(null);
      setActiveTransformBox(null);
      if (!op) return;

      const endScreen: Point = [event.point.x, event.point.y];
      const endPx = lngLatToPixel([event.lngLat.lng, event.lngLat.lat], mapContext);
      const distance = Math.hypot(endScreen[0] - op.startScreen[0], endScreen[1] - op.startScreen[1]);

      if (op.type === "pan") {
        map.getCanvas().style.cursor = selectPanInverted ? "grab" : "default";
        return;
      }

      if (op.type === "visual_prompt_draw") {
        if (distance < 5) {
          // 短位移点击：若命中了已有的检测框则直接点选高亮，否则取消选择
          const isAdditive = event.originalEvent.ctrlKey || event.originalEvent.metaKey || event.originalEvent.shiftKey;
          const hit = op.targetItemId ? items.find((i) => i.id === op.targetItemId) : findItemAtPx(endPx);
          if (hit) {
            onSelect(hit.id, isAdditive);
          } else if (!isAdditive) {
            onSelectMany([]);
          }
          return;
        }
        const box = clampBox(
          [
            Math.min(op.startPx[0], endPx[0]),
            Math.min(op.startPx[1], endPx[1]),
            Math.max(op.startPx[0], endPx[0]),
            Math.max(op.startPx[1], endPx[1]),
          ],
          mapContext,
        );
        if (box[2] - box[0] >= 4 && box[3] - box[1] >= 4) {
          onVisualPromptBox?.(box);
        }
        return;
      }

      if (op.type === "draw") {
        if (distance < 5) return;
        const box = clampBox(
          [
            Math.min(op.startPx[0], endPx[0]),
            Math.min(op.startPx[1], endPx[1]),
            Math.max(op.startPx[0], endPx[0]),
            Math.max(op.startPx[1], endPx[1]),
          ],
          mapContext,
        );
        if (box[2] - box[0] >= 4 && box[3] - box[1] >= 4) {
          onAddBox(box);
        }
        return;
      }

      if (op.type === "move" && op.targetItemId && op.originalBox) {
        if (distance >= 3) {
          const dx = endPx[0] - op.startPx[0];
          const dy = endPx[1] - op.startPx[1];
          const finalBox = clampBox(
            [
              op.originalBox[0] + dx,
              op.originalBox[1] + dy,
              op.originalBox[2] + dx,
              op.originalBox[3] + dy,
            ],
            mapContext,
          );
          if (finalBox[2] - finalBox[0] >= 4 && finalBox[3] - finalBox[1] >= 4) {
            onUpdateBox(op.targetItemId, finalBox);
          }
        }
        return;
      }

      if (op.type === "marquee") {
        if (distance >= 6) {
          const minPxX = Math.min(op.startPx[0], endPx[0]);
          const minPxY = Math.min(op.startPx[1], endPx[1]);
          const maxPxX = Math.max(op.startPx[0], endPx[0]);
          const maxPxY = Math.max(op.startPx[1], endPx[1]);

          const matchedIds = items
            .filter((item) => {
              if (hiddenCategories.includes(item.species) || !item.box_px || item.box_px.length !== 4) return false;
              const [x1, y1, x2, y2] = item.box_px;
              return !(x2 < minPxX || x1 > maxPxX || y2 < minPxY || y1 > maxPxY);
            })
            .map((item) => item.id);

          onSelectMany(matchedIds);
        } else {
          // 单击空白区域：清空选择
          const isAdditive = event.originalEvent.ctrlKey || event.originalEvent.metaKey || event.originalEvent.shiftKey;
          if (!isAdditive) {
            onSelectMany([]);
          }
        }
      }
    };

    // 空格键临时抓手
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.code !== "Space" || event.repeat) return;
      spacePanRef.current = true;
      map.getCanvas().style.cursor = "grab";
    };
    const onKeyUp = (event: KeyboardEvent) => {
      if (event.code !== "Space") return;
      spacePanRef.current = false;
      map.getCanvas().style.cursor = activeTool === "draw" ? "crosshair" : selectPanInverted ? "grab" : "default";
    };

    map.on("mousemove", onMouseMove);
    map.on("mousedown", onMouseDown);
    map.on("mouseup", onMouseUp);
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);

    return () => {
      map.off("mousemove", onMouseMove);
      map.off("mousedown", onMouseDown);
      map.off("mouseup", onMouseUp);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [
    ready,
    activeTool,
    selectPanInverted,
    mapContext,
    items,
    hiddenCategories,
    selectedIds,
    findItemAtPx,
    onAddBox,
    onSelect,
    onSelectMany,
    onUpdateBox,
    isTransforming,
  ]);

  // 计算当前选中框在屏幕上的像素坐标及 8 个控制点位置
  const transformOverlay = useMemo(() => {
    const map = mapRef.current;
    if (!map || !ready || activeTool !== "select" || !activeItem || activeItem.frozen) return null;

    const boxPx = activeTransformBox ?? (activeItem.box_px?.map(Number) as Box);
    if (!boxPx || boxPx.length !== 4) return null;

    // 转换为屏幕坐标
    const nwLngLat = pixelToLngLat([boxPx[0], boxPx[1]], mapContext);
    const seLngLat = pixelToLngLat([boxPx[2], boxPx[3]], mapContext);

    const nwScreen = map.project(new maplibregl.LngLat(nwLngLat[0], nwLngLat[1]));
    const seScreen = map.project(new maplibregl.LngLat(seLngLat[0], seLngLat[1]));

    const left = Math.min(nwScreen.x, seScreen.x);
    const top = Math.min(nwScreen.y, seScreen.y);
    const width = Math.abs(seScreen.x - nwScreen.x);
    const height = Math.abs(seScreen.y - nwScreen.y);

    const handles: Array<{ key: HandleKey; x: number; y: number }> = [
      { key: "nw", x: left, y: top },
      { key: "n", x: left + width / 2, y: top },
      { key: "ne", x: left + width, y: top },
      { key: "e", x: left + width, y: top + height / 2 },
      { key: "se", x: left + width, y: top + height },
      { key: "s", x: left + width / 2, y: top + height },
      { key: "sw", x: left, y: top + height },
      { key: "w", x: left, y: top + height / 2 },
    ];

    return { left, top, width, height, handles, boxPx, item: activeItem };
  }, [ready, activeTool, activeItem, activeTransformBox, mapContext, viewEpoch]);

  // 计算当前鼠标悬停的未选中框（用于唤醒左上角标签）
  const hoveredItem = useMemo(() => {
    if (!hoveredId || (activeItem && hoveredId === activeItem.id)) return null;
    return items.find((item) => item.id === hoveredId && !hiddenCategories.includes(item.species) && !hiddenItemIds.includes(item.id) && item.box_px?.length === 4) ?? null;
  }, [hoveredId, activeItem, items, hiddenCategories, hiddenItemIds]);

  // 计算鼠标悬停框在屏幕上的位置
  const hoverOverlay = useMemo(() => {
    const map = mapRef.current;
    if (!map || !ready || !hoveredItem) return null;

    const boxPx = hoveredItem.box_px?.map(Number) as Box;
    if (!boxPx || boxPx.length !== 4) return null;

    const nwLngLat = pixelToLngLat([boxPx[0], boxPx[1]], mapContext);
    const seLngLat = pixelToLngLat([boxPx[2], boxPx[3]], mapContext);

    const nwScreen = map.project(new maplibregl.LngLat(nwLngLat[0], nwLngLat[1]));
    const seScreen = map.project(new maplibregl.LngLat(seLngLat[0], seLngLat[1]));

    const left = Math.min(nwScreen.x, seScreen.x);
    const top = Math.min(nwScreen.y, seScreen.y);
    const width = Math.abs(seScreen.x - nwScreen.x);
    const height = Math.abs(seScreen.y - nwScreen.y);

    return { left, top, width, height, item: hoveredItem };
  }, [ready, hoveredItem, mapContext, viewEpoch]);

  // 处理 8 方向手柄指针拖拽变形
  const handlePointerDown = (handleKey: HandleKey, event: React.PointerEvent) => {
    event.stopPropagation();
    event.preventDefault();
    if (!activeItem || !activeItem.box_px) return;

    (event.target as HTMLElement).setPointerCapture(event.pointerId);
    setIsTransforming(true);

    const map = mapRef.current;
    const originalBox = [...activeItem.box_px] as Box;

    const onPointerMove = (moveEvt: PointerEvent) => {
      if (!map) return;
      const currentContainerRect = containerRef.current?.getBoundingClientRect();
      if (!currentContainerRect) return;

      const screenX = moveEvt.clientX - currentContainerRect.left;
      const screenY = moveEvt.clientY - currentContainerRect.top;

      const mapLngLat = map.unproject([screenX, screenY]);
      const currentPx = lngLatToPixel([mapLngLat.lng, mapLngLat.lat], mapContext);

      const nextBox = resizeBox(originalBox, handleKey, currentPx, mapContext);
      setActiveTransformBox(nextBox);
    };

    const onPointerUp = (upEvt: PointerEvent) => {
      setIsTransforming(false);
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);

      const currentContainerRect = containerRef.current?.getBoundingClientRect();
      if (currentContainerRect && map) {
        const screenX = upEvt.clientX - currentContainerRect.left;
        const screenY = upEvt.clientY - currentContainerRect.top;
        const mapLngLat = map.unproject([screenX, screenY]);
        const currentPx = lngLatToPixel([mapLngLat.lng, mapLngLat.lat], mapContext);
        const finalBox = resizeBox(originalBox, handleKey, currentPx, mapContext);
        if (finalBox[2] - finalBox[0] >= 4 && finalBox[3] - finalBox[1] >= 4) {
          onUpdateBox(activeItem.id, finalBox);
        }
      }
      setActiveTransformBox(null);
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
  };

  useImperativeHandle(
    ref,
    () => ({
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
    }),
    [mapContext],
  );

  return (
    <div className="review-map-shell">
      <div ref={containerRef} className="review-map" />

      {/* 框选与画框交互辅助层 */}
      {dragBox ? (
        <div
          className={`review-drag-box review-drag-box--${activeTool}`}
          style={{
            left: dragBox.left,
            top: dragBox.top,
            width: dragBox.width,
            height: dragBox.height,
          }}
        />
      ) : null}

      {/* 选中对象的 8 方向专业控制手柄与实时尺寸标注 */}
      {transformOverlay ? (
        <div className="review-transform-overlay">
          <div
            className="review-transform-box"
            style={{
              left: transformOverlay.left,
              top: transformOverlay.top,
              width: transformOverlay.width,
              height: transformOverlay.height,
            }}
          >
            {/* 树种与置信度轻量级标签：无背景框、文字描边、跟随缩放、高级别隐藏、优雅间距 */}
            {(() => {
              const currentZoom = mapRef.current?.getZoom() ?? 15;
              // 当缩放级别太低（视野太大/框太小）时直接不显示文字
              if (currentZoom < 13.8 || transformOverlay.width < 22 || transformOverlay.height < 22) return null;
              const catObj = categories.find((c) => c.id === transformOverlay.item.species || c.display_name === transformOverlay.item.species);
              const catName = catObj?.display_name || transformOverlay.item.species || "未命名";
              const catColor = catObj?.color || "#52c99a";
              const confVal = transformOverlay.item.confidence != null ? Number(transformOverlay.item.confidence).toFixed(2) : "";
              const dynamicFontSize = Math.max(11, Math.min(18, Math.round(13 * (currentZoom / 15))));

              return (
                <div
                  className="review-transform-tag"
                  style={{
                    fontSize: dynamicFontSize,
                  }}
                >
                  <span className="review-transform-tag__dot" style={{ backgroundColor: catColor }} />
                  <span className="review-transform-tag__species">{catName}</span>
                  {confVal ? <span className="review-transform-tag__conf">{confVal}</span> : null}
                </div>
              );
            })()}
          </div>

          {/* 8 个控制点位 */}
          {transformOverlay.handles.map(({ key, x, y }) => (
            <div
              key={key}
              className={`review-transform-handle handle-${key}`}
              style={{
                left: x,
                top: y,
                cursor: HANDLE_CURSORS[key],
              }}
              onPointerDown={(event) => handlePointerDown(key, event)}
              aria-label={`调整检测框 ${key}`}
            />
          ))}
        </div>
      ) : null}

      {/* 鼠标在画布上活动进入任何框时，即时唤醒左上角标签 */}
      {hoverOverlay && (!transformOverlay || hoverOverlay.item.id !== transformOverlay.item.id) ? (
        <div
          className="review-transform-box is-hover-overlay"
          style={{
            left: hoverOverlay.left,
            top: hoverOverlay.top,
            width: hoverOverlay.width,
            height: hoverOverlay.height,
            pointerEvents: "none",
          }}
        >
          {(() => {
            const currentZoom = mapRef.current?.getZoom() ?? 15;
            if (currentZoom < 13.8 || hoverOverlay.width < 20 || hoverOverlay.height < 20) return null;
            const catObj = categories.find((c) => c.id === hoverOverlay.item.species || c.display_name === hoverOverlay.item.species);
            const catName = catObj?.display_name || hoverOverlay.item.species || "未命名";
            const catColor = catObj?.color || "#52c99a";
            const confVal = hoverOverlay.item.confidence != null ? Number(hoverOverlay.item.confidence).toFixed(2) : "";
            const dynamicFontSize = Math.max(11, Math.min(18, Math.round(13 * (currentZoom / 15))));

            return (
              <div
                className="review-transform-tag review-transform-tag--hover"
                style={{
                  fontSize: dynamicFontSize,
                }}
              >
                <span className="review-transform-tag__dot" style={{ backgroundColor: catColor }} />
                <span className="review-transform-tag__species">{catName}</span>
                {confVal ? <span className="review-transform-tag__conf">{confVal}</span> : null}
              </div>
            );
          })()}
        </div>
      ) : null}

      {/* AI 范围指标：位于虚线框内部右下角，无背景框，乘号严格对齐 */}
      {(() => {
        const map = mapRef.current;
        if (!map || !ready || !regionMetricsVisible) return null;
        const center = map.getCenter();
        const centerPx = lngLatToPixel([center.lng, center.lat], mapContext);
        const half = regionSidePx / 2;
        const boxPx = [
          Math.max(0, centerPx[0] - half),
          Math.max(0, centerPx[1] - half),
          Math.min(mapContext.pixel_width, centerPx[0] + half),
          Math.min(mapContext.pixel_height, centerPx[1] + half),
        ];
        const nwLngLat = pixelToLngLat([boxPx[0], boxPx[1]], mapContext);
        const seLngLat = pixelToLngLat([boxPx[2], boxPx[3]], mapContext);
        const nwScreen = map.project(new maplibregl.LngLat(nwLngLat[0], nwLngLat[1]));
        const seScreen = map.project(new maplibregl.LngLat(seLngLat[0], seLngLat[1]));

        // 当虚线框在屏幕上的尺寸过小时优雅隐藏，避免缩小时的视觉堆叠
        const screenW = Math.abs(seScreen.x - nwScreen.x);
        const screenH = Math.abs(seScreen.y - nwScreen.y);
        if (screenW < 52 || screenH < 52) return null;

        const currentZoom = map.getZoom();
        const metricScale = Math.max(0.72, Math.min(1.15, currentZoom / 18));
        const pxW = Math.round(boxPx[2] - boxPx[0]);
        const pxH = Math.round(boxPx[3] - boxPx[1]);
        const mW = (pxW * mapContext.gsd).toFixed(1);
        const mH = (pxH * mapContext.gsd).toFixed(1);

        return (
          <div
            className="review-region-metric-tag"
            style={{
              left: seScreen.x - 3,
              top: seScreen.y - 3,
              transform: `translate(-100%, -100%) scale(${metricScale})`,
              transformOrigin: "bottom right",
            }}
            aria-live="polite"
          >
            <div className="review-region-metric-row">
              <span className="review-region-metric-label">px:</span>
              <span className="review-region-metric-val">{pxW}</span>
              <span className="review-region-metric-times">×</span>
              <span className="review-region-metric-val">{pxH}</span>
            </div>
            <div className="review-region-metric-row">
              <span className="review-region-metric-label">米:</span>
              <span className="review-region-metric-val">{mW}</span>
              <span className="review-region-metric-times">×</span>
              <span className="review-region-metric-val">{mH}</span>
            </div>
          </div>
        );
      })()}
    </div>
  );
});

// 图层初始化配置：高对比度纯线框 + 极低填充 + 醒目轮廓
function addReviewLayers(map: maplibregl.Map, effectiveGeometry?: EffectiveAreaGeometry | null) {
  map.addSource(EFFECTIVE_SOURCE, { type: "geojson", data: featureCollection(effectiveGeometry) });
  map.addLayer({
    id: "review-effective-fill",
    type: "fill",
    source: EFFECTIVE_SOURCE,
    layout: { visibility: "none" },
    paint: { "fill-color": "#46a171", "fill-opacity": 0.07 },
  });
  map.addLayer({
    id: "review-effective-line",
    type: "line",
    source: EFFECTIVE_SOURCE,
    layout: { visibility: "none" },
    paint: { "line-color": "#d9fff0", "line-width": 2, "line-dasharray": [3, 2] },
  });

  map.addSource(REGION_SOURCE, { type: "geojson", data: featureCollection() });
  map.addLayer({
    id: "review-region-line",
    type: "line",
    source: REGION_SOURCE,
    layout: { visibility: "none" },
    paint: {
      "line-color": "#f0c96a",
      "line-width": 1.5,
      "line-opacity": 0.9,
      "line-dasharray": [3, 2],
    },
  });

  // 主检测框数据源
  map.addSource(ITEM_SOURCE, { type: "geojson", data: featureCollection() });

  // 极淡填充（默认 0.04，hover 0.08，选中 0.12，绝不遮挡遥感影像）
  map.addLayer({
    id: "review-items-fill",
    type: "fill",
    source: ITEM_SOURCE,
    paint: {
      "fill-color": ["get", "color"],
      "fill-opacity": [
        "case",
        ["boolean", ["get", "frozen"], false],
        0,
        ["boolean", ["get", "selected"], false],
        0.12,
        ["boolean", ["get", "hovered"], false],
        0.08,
        0.04,
      ],
    },
  });

  // 高对比度纯线框（默认 2px 实线，hover 2.4px，选中 2.8px）
  map.addLayer({
    id: "review-items-line",
    type: "line",
    source: ITEM_SOURCE,
    paint: {
      "line-color": ["get", "color"],
      "line-width": [
        "case",
        ["boolean", ["get", "selected"], false],
        2.8,
        ["boolean", ["get", "hovered"], false],
        2.4,
        2.0,
      ],
      "line-opacity": ["case", ["boolean", ["get", "frozen"], false], 0.7, 0.98],
    },
  });

  // 选中状态双重高亮外光晕（白色 1.2px，外偏移 2.5px，在暗色与亮色地表均极其显眼）
  map.addLayer({
    id: "review-items-selected",
    type: "line",
    source: ITEM_SOURCE,
    filter: ["==", ["get", "selected"], true],
    paint: {
      "line-color": "#ffffff",
      "line-width": 1.2,
      "line-offset": 2.5,
      "line-opacity": 0.95,
    },
  });

  // 候选预览图层
  map.addSource(CANDIDATE_SOURCE, { type: "geojson", data: featureCollection() });
  map.addLayer({
    id: "review-candidates-fill",
    type: "fill",
    source: CANDIDATE_SOURCE,
    paint: { "fill-color": ["get", "color"], "fill-opacity": 0.12 },
  });
  map.addLayer({
    id: "review-candidates-line",
    type: "line",
    source: CANDIDATE_SOURCE,
    paint: { "line-color": ["get", "color"], "line-width": 2, "line-dasharray": [3, 2] },
  });
}

function itemCollection(
  items: Array<ReviewItem & { __selected?: boolean; __hovered?: boolean }>,
  colors: Map<string, string>,
  context: ReviewMapContext,
  candidate = false,
): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: items.flatMap((item): GeoJSON.Feature[] => {
      const box = item.box_wgs84;
      const pixelBox = item.box_px?.length === 4 ? (item.box_px.map(Number) as Box) : null;
      if ((!box || box.length !== 4) && !pixelBox) return [];
      const geometry =
        (candidate || (item.source === "ai" && !item.frozen)) && pixelBox
          ? ellipsePolygon(pixelBox, context)
          : box && box.length === 4
            ? geographicBoxPolygon(box.map(Number) as Box)
            : pixelBoxPolygon(pixelBox as Box, context);
      return [
        {
          type: "Feature",
          properties: {
            id: item.id,
            species: item.species,
            status: item.status,
            frozen: Boolean(item.frozen),
            selected: Boolean(item.__selected),
            hovered: Boolean(item.__hovered),
            candidate,
            color: colors.get(item.species) ?? "#72bc8f",
          },
          geometry,
        },
      ];
    }),
  };
}

function featureCollection(geometry?: EffectiveAreaGeometry | null): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: geometry
      ? [{ type: "Feature", properties: {}, geometry: geometry as GeoJSON.Polygon | GeoJSON.MultiPolygon }]
      : [],
  };
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
  return [
    Math.max(0, Math.min(context.pixel_width, u * context.pixel_width)),
    Math.max(0, Math.min(context.pixel_height, v * context.pixel_height)),
  ];
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
  return {
    type: "Polygon",
    coordinates: [
      [
        [west, south],
        [east, south],
        [east, north],
        [west, north],
        [west, south],
      ],
    ],
  };
}

function ellipsePolygon(box: Box, context: ReviewMapContext): GeoJSON.Polygon {
  const [x1, y1, x2, y2] = clampBox(box, context);
  const centerX = (x1 + x2) / 2;
  const centerY = (y1 + y2) / 2;
  const radiusX = (x2 - x1) / 2;
  const radiusY = (y2 - y1) / 2;
  const ring: Point[] = [];
  for (let index = 0; index <= 32; index += 1) {
    const angle = (index / 32) * Math.PI * 2;
    ring.push(pixelToLngLat([centerX + Math.cos(angle) * radiusX, centerY + Math.sin(angle) * radiusY], context));
  }
  return { type: "Polygon", coordinates: [ring] };
}

function clampBox(box: Box, context: ReviewMapContext): Box {
  const x1 = Math.max(0, Math.min(context.pixel_width - 1, Math.min(box[0], box[2])));
  const y1 = Math.max(0, Math.min(context.pixel_height - 1, Math.min(box[1], box[3])));
  const x2 = Math.max(1, Math.min(context.pixel_width, Math.max(box[0], box[2])));
  const y2 = Math.max(1, Math.min(context.pixel_height, Math.max(box[1], box[3])));
  return [x1, y1, x2, y2];
}

function resizeBox(original: Box, handle: HandleKey, point: Point, context: ReviewMapContext): Box {
  let [x1, y1, x2, y2] = original;
  if (handle.includes("w")) x1 = Math.min(x2 - 4, point[0]);
  if (handle.includes("e")) x2 = Math.max(x1 + 4, point[0]);
  if (handle.includes("n")) y1 = Math.min(y2 - 4, point[1]);
  if (handle.includes("s")) y2 = Math.max(y1 + 4, point[1]);
  return clampBox([x1, y1, x2, y2], context);
}

function setRoadOverlay(map: maplibregl.Map | null, visible: boolean) {
  if (!map) return;
  if (!visible) {
    if (map.getLayer("review-road")) map.removeLayer("review-road");
    if (map.getSource(ROAD_SOURCE)) map.removeSource(ROAD_SOURCE);
    return;
  }
  if (!map.getSource(ROAD_SOURCE)) {
    map.addSource(ROAD_SOURCE, { type: "raster", tiles: ROAD_OVERLAY.tiles, tileSize: ROAD_OVERLAY.tileSize ?? 256 });
  }
  if (!map.getLayer("review-road")) {
    map.addLayer(
      { id: "review-road", type: "raster", source: ROAD_SOURCE, paint: { "raster-opacity": 0.22 } },
      map.getLayer("review-effective-fill") ? "review-effective-fill" : undefined,
    );
  }
}
