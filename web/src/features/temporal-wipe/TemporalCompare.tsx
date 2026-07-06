import type { CSSProperties } from "react";
import { Empty } from "antd";
import { TemporalWipe, type WipeSide } from "../../shared/ui/TemporalWipe";
import { MapStage } from "../../shared/ui/MapStage";
import {
  rasterBasemap,
  type GeoJsonLayerSpec,
  type LngLat,
  type RasterBasemap,
} from "../../shared/map-core";
import type { Phase } from "../../entities/phase";
import { useObservations } from "../../entities/observation";
import { useTractImagery } from "../../entities/tract";
import type { TractImagery } from "../../shared/api";
import { PhaseTimeline } from "./PhaseTimeline";

const COLOR_BEFORE = "#f0b84f";
const COLOR_AFTER = "#33b27b";

// 时相卷帘编排器(受控): range 由父级持有, 与变化量化面板共用单一真相。
// 根据选中的两个时相, 分别拉取树冠观测作为卷帘两侧叠加。
// 数据缝(P2): 目前以树冠矢量展示变化; 待后端多时相栓格影像就绪后, 刷开可直接对比真影像。
export function TemporalCompare({
  phases,
  range,
  onRangeChange,
  center,
  zoom,
}: {
  phases: Phase[];
  range: [number, number];
  onRangeChange: (v: [number, number]) => void;
  center: LngLat;
  zoom: number;
}) {
  const beforePhase = phases[range[0]];
  const afterPhase = phases[range[1]];
  const beforeObs = useObservations(beforePhase?.id, "crown");
  const afterObs = useObservations(afterPhase?.id, "crown");
  // 各时相真影像底图(后端就绪则刷开真影像, 否则回退默认底图)。
  const beforeImagery = useTractImagery(beforePhase?.id);
  const afterImagery = useTractImagery(afterPhase?.id);

  if (phases.length === 0) {
    return (
      <div style={CENTER}>
        <Empty description="该地点暂无时相数据" />
      </div>
    );
  }

  // 单一时相: 降级为现状展示, 不渲染卷帘。
  if (phases.length === 1) {
    const only = phases[0];
    const overlay = buildOverlay(
      "obs-only",
      only.id,
      beforeObs.data,
      COLOR_AFTER,
    );
    return (
      <div style={STAGE}>
        <MapStage center={center} zoom={zoom} overlay={overlay} />
        <div style={SINGLE_HINT}>
          单一时相（{only.time || "未知"}），暂无可对比项
        </div>
      </div>
    );
  }

  const before: WipeSide = {
    overlay: buildOverlay(
      "obs-before",
      beforePhase?.id,
      beforeObs.data,
      COLOR_BEFORE,
    ),
    basemap: imageryToBasemap(beforeImagery.data),
  };
  const after: WipeSide = {
    overlay: buildOverlay(
      "obs-after",
      afterPhase?.id,
      afterObs.data,
      COLOR_AFTER,
    ),
    basemap: imageryToBasemap(afterImagery.data),
  };

  return (
    <div style={STAGE}>
      <TemporalWipe before={before} after={after} center={center} zoom={zoom} />
      <div style={TIMELINE_PANEL}>
        <PhaseTimeline
          phases={phases}
          range={range}
          onRangeChange={onRangeChange}
        />
      </div>
    </div>
  );
}

function imageryToBasemap(img?: TractImagery): RasterBasemap | undefined {
  if (!img || !img.available || !img.tiles || img.tiles.length === 0) {
    return undefined;
  }
  return rasterBasemap(img.tiles, {
    tileSize: img.tile_size,
    attribution: img.attribution ?? undefined,
  });
}

function buildOverlay(
  id: string,
  phaseId: string | undefined,
  data: unknown,
  color: string,
): GeoJsonLayerSpec | undefined {
  if (!phaseId || !data) return undefined;
  return {
    id,
    kind: "line",
    data: data as GeoJsonLayerSpec["data"],
    color,
    opacity: 0.86,
    lineWidth: 1.15,
  };
}

const STAGE: CSSProperties = { position: "absolute", inset: 0 };
const CENTER: CSSProperties = {
  display: "flex",
  justifyContent: "center",
  alignItems: "center",
  height: "100%",
};
const TIMELINE_PANEL: CSSProperties = {
  position: "absolute",
  bottom: 18,
  left: "50%",
  transform: "translateX(-50%)",
  width: "min(340px, calc(100% - 96px))",
  zIndex: 5,
  borderRadius: 12,
  background: "var(--glass-bg)",
  border: "1px solid var(--glass-border)",
  boxShadow: "var(--glass-shadow), var(--glass-inner)",
  backdropFilter: "blur(16px) saturate(150%)",
};
const SINGLE_HINT: CSSProperties = {
  position: "absolute",
  top: 16,
  left: "50%",
  transform: "translateX(-50%)",
  zIndex: 5,
  background: "rgba(16,48,43,0.85)",
  color: "#fff",
  padding: "4px 14px",
  borderRadius: 999,
  fontSize: 12,
};
