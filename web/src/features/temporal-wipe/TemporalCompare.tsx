import type { CSSProperties } from "react";
import { Card, Empty } from "antd";
import { TemporalWipe, type WipeSide } from "../../shared/ui/TemporalWipe";
import { MapStage } from "../../shared/ui/MapStage";
import type { GeoJsonLayerSpec, LngLat } from "../../shared/map-core";
import type { Phase } from "../../entities/phase";
import { useObservations } from "../../entities/observation";
import { PhaseSlider } from "./PhaseSlider";

const COLOR_BEFORE = "#c9a24b"; // 滩泥(旧时相)
const COLOR_AFTER = "#3e8e5a"; // 冠绿(新时相)

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
  };
  const after: WipeSide = {
    overlay: buildOverlay(
      "obs-after",
      afterPhase?.id,
      afterObs.data,
      COLOR_AFTER,
    ),
  };

  return (
    <div style={STAGE}>
      <TemporalWipe before={before} after={after} center={center} zoom={zoom} />
      <Card style={SLIDER_PANEL} styles={SLIDER_CARD_STYLES}>
        <PhaseSlider phases={phases} value={range} onChange={onRangeChange} />
      </Card>
    </div>
  );
}

function buildOverlay(
  id: string,
  phaseId: string | undefined,
  data: unknown,
  color: string,
): GeoJsonLayerSpec | undefined {
  if (!phaseId || !data) return undefined;
  return { id, kind: "polygon", data: data as GeoJsonLayerSpec["data"], color };
}

const STAGE: CSSProperties = { position: "absolute", inset: 0 };
const CENTER: CSSProperties = {
  display: "flex",
  justifyContent: "center",
  alignItems: "center",
  height: "100%",
};
const SLIDER_PANEL: CSSProperties = {
  position: "absolute",
  top: 16,
  left: "50%",
  transform: "translateX(-50%)",
  width: "min(560px, calc(100% - 360px))",
  zIndex: 5,
  boxShadow: "var(--shadow-2)",
};
const SLIDER_BODY: CSSProperties = { padding: "8px 4px 0" };
const SLIDER_CARD_STYLES = { body: SLIDER_BODY };
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
