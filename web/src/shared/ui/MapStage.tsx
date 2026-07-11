import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  boundsOf,
  createMapController,
  defaultBasemap,
  type GeoJsonLayerSpec,
  type MapController,
} from "../map-core";

// 地图舞台: 将 map-core 控制器挂载到 DOM, 并通过 onReady 将控制器交给业务。
// 业务页(overview/atlas)只面向 MapController 接口操作, 不接触 MapLibre。
// 可选 overlay: 单一矢量图层(如单一时相的树冠)。
export function MapStage({
  center = [113.3, 22.5],
  zoom = 7,
  overlay,
  onReady,
}: {
  center?: [number, number];
  zoom?: number;
  overlay?: GeoJsonLayerSpec;
  onReady?: (map: MapController) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const controllerRef = useRef<MapController | null>(null);
  const overlayIdRef = useRef<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || controllerRef.current) return;
    const controller = createMapController();
    controllerRef.current = controller;
    let disposed = false;
    controller
      .init({ container: el, center, zoom, basemap: defaultBasemap() })
      .then(() => {
        if (disposed) return;
        setReady(true);
        onReady?.(controller);
      });
    return () => {
      disposed = true;
      controller.destroy();
      controllerRef.current = null;
      overlayIdRef.current = null;
      setReady(false);
    };
    // 仅挂载一次。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const controller = controllerRef.current;
    if (!controller || !ready) return;
    if (!overlay) {
      if (overlayIdRef.current) controller.removeLayer(overlayIdRef.current);
      overlayIdRef.current = null;
      return;
    }
    if (overlayIdRef.current && overlayIdRef.current !== overlay.id) {
      controller.removeLayer(overlayIdRef.current);
    }
    controller.setGeoJsonLayer(overlay);
    overlayIdRef.current = overlay.id;
    const b = boundsOf(overlay.data);
    if (b) controller.fitBounds(b, 40);
  }, [ready, overlay]);

  return <div ref={containerRef} style={STAGE} />;
}

const STAGE: CSSProperties = { position: "absolute", inset: 0 };
