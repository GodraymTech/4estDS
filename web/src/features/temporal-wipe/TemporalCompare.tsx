import { useMemo } from "react";
import type { CSSProperties } from "react";
import { Empty } from "antd";
import { TemporalWipe, type TemporalWipeApi, type WipeSide } from "../../shared/ui/TemporalWipe";
import { MapStage } from "../../shared/ui/MapStage";
import {
  rasterBasemap,
  type GeoJsonLayerSpec,
  type LngLat,
  type RasterBasemap,
  type RasterOverlaySpec,
} from "../../shared/map-core";
import type { Phase } from "../../entities/phase";
import { useObservations } from "../../entities/observation";
import { useTractImagery } from "../../entities/tract";
import type { TractImagery } from "../../shared/api";
import type { FeatureCollection } from "../../shared/api";
import { liveFeatureCollection } from "../../shared/lib/species";
import { PhaseTimeline } from "./PhaseTimeline";

const COLOR_BEFORE = "#f0b84f";
const COLOR_AFTER = "#33b27b";
const BEFORE_SPECIES_COLORS = ["#f0b84f", "#e76f51", "#d1495b", "#b56576", "#9c6644", "#c77dff"];
const AFTER_SPECIES_COLORS = ["#33b27b", "#00a6a6", "#2a9d8f", "#4cc9f0", "#3a86ff", "#43aa8b"];

// 时相卷帘编排器(受控): range 由父级持有, 与变化量化面板共用单一真相。
// 根据选中的两个时相, 分别拉取树冠观测作为卷帘两侧叠加。
// 数据缝(P2): 目前以树冠矢量展示变化; 待后端多时相栓格影像就绪后, 刷开可直接对比真影像。
export function TemporalCompare({
  phases,
  range,
  onRangeChange,
  center,
  zoom,
  basemap,
  roadOverlay,
  onWipeApi,
  showDetections,
  selectedSpecies,
}: {
  phases: Phase[];
  range: [number, number];
  onRangeChange: (v: [number, number]) => void;
  center: LngLat;
  zoom: number;
  basemap?: RasterBasemap;
  roadOverlay?: RasterOverlaySpec | null;
  onWipeApi?: (api: TemporalWipeApi | null) => void;
  showDetections: boolean;
  selectedSpecies: string[];
}) {
  const beforePhase = phases[range[0]];
  const afterPhase = phases[range[1]];
  const beforeObs = useObservations(beforePhase?.id, "crown");
  const afterObs = useObservations(afterPhase?.id, "crown");
  // 各时相真影像底图(后端就绪则刷开真影像, 否则回退默认底图)。
  const beforeImagery = useTractImagery(beforePhase?.id);
  const afterImagery = useTractImagery(afterPhase?.id);

  const before = useMemo<WipeSide>(() => ({
    overlay: buildOverlay(
      "obs-before",
      beforePhase?.id,
      beforeObs.data,
      COLOR_BEFORE,
      showDetections,
      selectedSpecies,
    ),
    basemap: imageryToBasemap(beforeImagery.data),
  }), [beforeImagery.data, beforeObs.data, beforePhase?.id, selectedSpecies, showDetections]);
  const after = useMemo<WipeSide>(() => ({
    overlay: buildOverlay(
      "obs-after",
      afterPhase?.id,
      afterObs.data,
      COLOR_AFTER,
      showDetections,
      selectedSpecies,
    ),
    basemap: imageryToBasemap(afterImagery.data),
  }), [afterImagery.data, afterObs.data, afterPhase?.id, selectedSpecies, showDetections]);
  const singleOverlay = useMemo(
    () => buildOverlay(
      "obs-only",
      phases[0]?.id,
      beforeObs.data,
      COLOR_AFTER,
      showDetections,
      selectedSpecies,
    ),
    [beforeObs.data, phases, selectedSpecies, showDetections],
  );

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
    return (
      <div style={STAGE}>
        <MapStage center={center} zoom={zoom} overlay={singleOverlay} />
        <div style={SINGLE_HINT}>
          单一时相（{only.time || "未知"}），暂无可对比项
        </div>
      </div>
    );
  }

  return (
    <div style={STAGE}>
      <TemporalWipe
        before={before}
        after={after}
        center={center}
        zoom={zoom}
        basemap={basemap}
        roadOverlay={roadOverlay}
        onApi={onWipeApi}
      />
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
  visible: boolean,
  selectedSpecies: string[],
): GeoJsonLayerSpec | undefined {
  if (!phaseId || !data || !visible || selectedSpecies.length === 0) return undefined;
  const allowed = new Set(selectedSpecies);
  const liveData = liveFeatureCollection(data as FeatureCollection);
  const features = (liveData?.features ?? []).filter((feature) => {
    const species = typeof feature.properties?.species === "string" && feature.properties.species.trim()
      ? feature.properties.species
      : "未知树种";
    return allowed.has(species);
  });
  return {
    id,
    kind: "line",
    data: { type: "FeatureCollection", features } as GeoJsonLayerSpec["data"],
    color: compareSpeciesColorExpression(selectedSpecies, color),
    opacity: 0.86,
    lineWidth: 1.15,
  };
}

function compareSpeciesColorExpression(species: string[], phaseColor: string): unknown[] {
  const palette = phaseColor === COLOR_BEFORE ? BEFORE_SPECIES_COLORS : AFTER_SPECIES_COLORS;
  const entries = species.flatMap((name, index) => [name, palette[index % palette.length]]);
  return ["match", ["coalesce", ["get", "species"], "未知树种"], ...entries, palette[0]];
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
