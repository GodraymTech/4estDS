import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { useNavigate } from "react-router-dom";
import { MapStage } from "../../shared/ui/MapStage";
import type { LngLat, MapController, MarkerSpec } from "../../shared/map-core";
import { useTracts, type Tract } from "../../entities/tract";
import { pointsBounds, tractCenter } from "./tractGeo";
import { createTractMarkerElement } from "./TractMarker";
import { TractProfileCard } from "./TractProfileCard";

interface Hovered {
  tract: Tract;
  x: number;
  y: number;
}

// 语义缩放总览图(一张图): 库中地块以倒水滴标记呈现,
// 悬停看 profile, 点击丝滑飞入该地块工作台(/atlas/:id)。
// (P2: 省市县 choropleth 边界图层 + 密集时聚合。)
export function OverviewMap() {
  const { data: tracts } = useTracts();
  const navigate = useNavigate();
  const mapRef = useRef<MapController | null>(null);
  const [ready, setReady] = useState(false);
  const [hovered, setHovered] = useState<Hovered | null>(null);

  const located = useMemo(() => {
    const out: Array<{ tract: Tract; center: LngLat }> = [];
    for (const t of tracts ?? []) {
      const center = tractCenter(t);
      if (center) out.push({ tract: t, center });
    }
    return out;
  }, [tracts]);

  const missing = (tracts?.length ?? 0) - located.length;

  const onReady = useCallback((map: MapController) => {
    mapRef.current = map;
    setReady(true);
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const specs: MarkerSpec[] = located.map(({ tract, center }) => {
      const element = createTractMarkerElement(Boolean(tract.active_run_id), {
        onClick: () => navigate("/atlas/" + tract.tract_id),
        onEnter: (rect) =>
          setHovered({ tract, x: rect.left + rect.width / 2, y: rect.top }),
        onLeave: () => setHovered(null),
      });
      return { id: tract.tract_id, lngLat: center, element };
    });
    map.setMarkers(specs);
    const bounds = pointsBounds(specs.map((s) => s.lngLat));
    if (bounds) map.fitBounds(bounds, 72);
  }, [ready, located, navigate]);

  return (
    <div style={STAGE}>
      <MapStage center={[113.3, 22.5]} zoom={7} onReady={onReady} />
      {hovered ? (
        <TractProfileCard tract={hovered.tract} x={hovered.x} y={hovered.y} />
      ) : null}
      {missing > 0 ? (
        <div style={BANNER}>
          {missing} 个地块待补充坐标（后端 /tracts 返回 center_lng/lat
          后自动上图）
        </div>
      ) : null}
    </div>
  );
}

const STAGE: CSSProperties = { position: "absolute", inset: 0 };
const BANNER: CSSProperties = {
  position: "absolute",
  bottom: 16,
  left: "50%",
  transform: "translateX(-50%)",
  zIndex: 5,
  background: "rgba(184,71,42,0.92)",
  color: "#fff",
  padding: "6px 14px",
  borderRadius: 999,
  fontSize: 12,
};
