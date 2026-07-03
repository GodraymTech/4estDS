import { useEffect, useRef } from "react";
import type { CSSProperties } from "react";
import {
  createMapController,
  defaultBasemap,
  type MapController,
} from "../map-core";

// 地图舞台: 将 map-core 控制器挂载到 DOM, 并通过 onReady 将控制器交给业务。
// 业务页(overview/atlas)只面向 MapController 接口操作, 不接触 MapLibre。
export function MapStage({
  center = [113.3, 22.5],
  zoom = 7,
  onReady,
}: {
  center?: [number, number];
  zoom?: number;
  onReady?: (map: MapController) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const controllerRef = useRef<MapController | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || controllerRef.current) return;
    const controller = createMapController();
    controllerRef.current = controller;
    let disposed = false;
    controller
      .init({ container: el, center, zoom, basemap: defaultBasemap() })
      .then(() => {
        if (!disposed) onReady?.(controller);
      });
    return () => {
      disposed = true;
      controller.destroy();
      controllerRef.current = null;
    };
    // 仅挂载一次。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <div ref={containerRef} style={STAGE} />;
}

const STAGE: CSSProperties = { position: "absolute", inset: 0 };
