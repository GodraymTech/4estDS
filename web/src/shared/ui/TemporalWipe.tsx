import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties, PointerEvent as ReactPointerEvent } from "react";
import {
  boundsOf,
  createMapController,
  defaultBasemap,
  type GeoJsonLayerSpec,
  type LngLat,
  type MapController,
  type RasterBasemap,
} from "../map-core";

// 卷帘一侧: 可选的矢量叠加图层 + 可选的该时相真影像底图。
export interface WipeSide {
  overlay?: GeoJsonLayerSpec;
  basemap?: RasterBasemap;
}

// 时相卷帘(Temporal Wipe) —— 产品签名交互。
// 实现: 上下叠放两个同步地图画布(下=旧时相, 上=新时相), 上层用 clip-path 真实裁切;
// 拖动分隔把手连续揭示。两图相机单向同步(主图可交互, 跟随图 interactive=false)。
export function TemporalWipe({
  before,
  after,
  center,
  zoom,
  basemap,
}: {
  before: WipeSide;
  after: WipeSide;
  center: LngLat;
  zoom: number;
  basemap?: RasterBasemap;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const beforeElRef = useRef<HTMLDivElement>(null);
  const afterElRef = useRef<HTMLDivElement>(null);
  const beforeCtrl = useRef<MapController | null>(null);
  const afterCtrl = useRef<MapController | null>(null);
  const dragging = useRef(false);
  const [ready, setReady] = useState(false);
  const [x, setX] = useState(0.5);

  // 只初始化一次: 创建两个控制器 + 相机单向同步。
  useEffect(() => {
    const bEl = beforeElRef.current;
    const aEl = afterElRef.current;
    if (!bEl || !aEl || beforeCtrl.current) return;
    const bm = basemap ?? defaultBasemap();
    const b = createMapController();
    const a = createMapController();
    beforeCtrl.current = b;
    afterCtrl.current = a;
    let disposed = false;
    Promise.all([
      b.init({ container: bEl, center, zoom, basemap: bm, interactive: true }),
      a.init({ container: aEl, center, zoom, basemap: bm, interactive: false }),
    ]).then(() => {
      if (disposed) return;
      a.jumpTo(b.getCamera());
      b.on("move", () => {
        const follower = afterCtrl.current;
        const leader = beforeCtrl.current;
        if (follower && leader) follower.jumpTo(leader.getCamera());
      });
      setReady(true);
    });
    return () => {
      disposed = true;
      b.destroy();
      a.destroy();
      beforeCtrl.current = null;
      afterCtrl.current = null;
      setReady(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 旧时相叠加(主图): 同时负责 fitBounds, 跟随图经 move 同步。
  useEffect(() => {
    const c = beforeCtrl.current;
    if (!c || !ready || !before.overlay) return;
    c.setGeoJsonLayer(before.overlay);
    const b = boundsOf(before.overlay.data);
    if (b) c.fitBounds(b, 48);
  }, [ready, before.overlay]);

  // 新时相叠加(跟随图): 仅设数据, 不单独 fit。
  useEffect(() => {
    const c = afterCtrl.current;
    if (!c || !ready || !after.overlay) return;
    c.setGeoJsonLayer(after.overlay);
  }, [ready, after.overlay]);

  // 各时相真影像底图热替换(就绪后按侧刷开)。
  useEffect(() => {
    const c = beforeCtrl.current;
    if (!c || !ready || !before.basemap) return;
    c.setBasemap(before.basemap);
  }, [ready, before.basemap]);

  useEffect(() => {
    const c = afterCtrl.current;
    if (!c || !ready || !after.basemap) return;
    c.setBasemap(after.basemap);
  }, [ready, after.basemap]);

  // 分隔把手拖动: 基于容器宽度换算比例。
  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      if (!dragging.current || !rootRef.current) return;
      const rect = rootRef.current.getBoundingClientRect();
      const frac = (e.clientX - rect.left) / rect.width;
      setX(Math.min(1, Math.max(0, frac)));
    };
    const onUp = () => {
      dragging.current = false;
    };
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
    return () => {
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
    };
  }, []);

  const onHandleDown = useCallback((e: ReactPointerEvent) => {
    dragging.current = true;
    e.preventDefault();
  }, []);

  const pct = x * 100;
  const afterStyle: CSSProperties = {
    ...MAP_LAYER,
    zIndex: 2,
    pointerEvents: "none",
    clipPath: "inset(0 0 0 " + pct + "%)",
  };
  const dividerStyle: CSSProperties = {
    ...DIVIDER,
    left: "calc(" + pct + "% - 1px)",
  };
  const handleStyle: CSSProperties = {
    ...HANDLE,
    left: "calc(" + pct + "% - 16px)",
  };

  return (
    <div ref={rootRef} style={ROOT}>
      <div ref={beforeElRef} style={MAP_LAYER} />
      <div ref={afterElRef} style={afterStyle} />
      <div style={dividerStyle} />
      <div
        style={handleStyle}
        onPointerDown={onHandleDown}
        role="slider"
        aria-label="时相卷帘分隔"
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
        tabIndex={0}
      >
        ⇄
      </div>
      <span style={LABEL_BEFORE}>旧时相</span>
      <span style={LABEL_AFTER}>新时相</span>
    </div>
  );
}

const ROOT: CSSProperties = {
  position: "absolute",
  inset: 0,
  overflow: "hidden",
};
const MAP_LAYER: CSSProperties = { position: "absolute", inset: 0 };
const DIVIDER: CSSProperties = {
  position: "absolute",
  top: 0,
  bottom: 0,
  width: 2,
  background: "#ffffff",
  boxShadow: "0 0 0 1px rgba(16,48,43,0.35)",
  zIndex: 3,
  pointerEvents: "none",
};
const HANDLE: CSSProperties = {
  position: "absolute",
  top: "50%",
  transform: "translateY(-50%)",
  width: 32,
  height: 32,
  borderRadius: "50%",
  background: "#0e6e63",
  color: "#ffffff",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  cursor: "ew-resize",
  zIndex: 4,
  boxShadow: "0 2px 8px rgba(16,48,43,0.35)",
  userSelect: "none",
};
const LABEL_BASE: CSSProperties = {
  position: "absolute",
  top: 12,
  padding: "2px 10px",
  borderRadius: 999,
  fontSize: 12,
  color: "#ffffff",
  zIndex: 3,
  pointerEvents: "none",
};
const LABEL_BEFORE: CSSProperties = {
  ...LABEL_BASE,
  left: 12,
  background: "rgba(201,162,75,0.92)",
};
const LABEL_AFTER: CSSProperties = {
  ...LABEL_BASE,
  right: 12,
  background: "rgba(62,142,90,0.92)",
};
