import { useCallback, useEffect, useMemo, useRef } from "react";
import type { CSSProperties } from "react";
import { Card, Space, Spin, Typography } from "antd";
import { MapStage } from "../../shared/ui/MapStage";
import { boundsOf, type MapController } from "../../shared/map-core";
import type { Phase } from "../../entities/phase";
import type { LngLat } from "../../shared/map-core";
import { useObservations } from "../../entities/observation";
import { detectPolygonChanges, splitByChange } from "./detect";

const { Text } = Typography;

const L_RETAINED = "chg-retained";
const L_LOST = "chg-lost";
const L_ADDED = "chg-added";
const C_ADDED = "#3e8e5a"; // 新增(造林/扩展)
const C_LOST = "#b8472a"; // 消失(枯死/砸伐)
const C_RETAINED = "#9fb0aa"; // 保留(背景)

function ha(m2: number): string {
  return (m2 / 10000).toFixed(2);
}

// 逐图斑变化视图: 单图展示两期叠分结果(新增/消失/保留三色分层) + 图例统计。
// 与卷帘共用 range(上层单一真相)。
export function ChangeDetectView({
  phases,
  range,
  center,
  zoom,
}: {
  phases: Phase[];
  range: [number, number];
  center: LngLat;
  zoom: number;
}) {
  const before = phases[range[0]];
  const after = phases[range[1]];
  const beforeObs = useObservations(before?.id, "crown");
  const afterObs = useObservations(after?.id, "crown");
  const loading = beforeObs.isFetching || afterObs.isFetching;
  const single = range[0] === range[1];

  const result = useMemo(
    () => detectPolygonChanges(beforeObs.data, afterObs.data),
    [beforeObs.data, afterObs.data],
  );

  const mapRef = useRef<MapController | null>(null);

  const draw = useCallback(() => {
    const map = mapRef.current;
    if (!map || !map.isReady()) return;
    const parts = splitByChange(result.features);
    map.setGeoJsonLayer({
      id: L_RETAINED,
      kind: "polygon",
      data: parts.retained,
      color: C_RETAINED,
    });
    map.setGeoJsonLayer({
      id: L_LOST,
      kind: "polygon",
      data: parts.lost,
      color: C_LOST,
    });
    map.setGeoJsonLayer({
      id: L_ADDED,
      kind: "polygon",
      data: parts.added,
      color: C_ADDED,
    });
    const b = boundsOf(result.features);
    if (b) map.fitBounds(b, 40);
  }, [result]);

  useEffect(() => {
    draw();
  }, [draw]);

  const onReady = useCallback(
    (map: MapController) => {
      mapRef.current = map;
      draw();
    },
    [draw],
  );

  return (
    <div style={STAGE}>
      <MapStage center={center} zoom={zoom} onReady={onReady} />
      <Card style={PANEL} styles={CARD_STYLES} title="图斑变化">
        {single ? (
          <Text type="secondary" style={SUB}>
            选择两个不同时相以逐图斑叠分。
          </Text>
        ) : loading ? (
          <div style={CENTER}>
            <Spin size="small" />
          </div>
        ) : (
          <Space direction="vertical" size={10} style={FULL}>
            <Legend
              color={C_ADDED}
              label="新增图斑"
              count={result.addedCount}
              area={ha(result.addedArea)}
              sign="+"
            />
            <Legend
              color={C_LOST}
              label="消失图斑"
              count={result.lostCount}
              area={ha(result.lostArea)}
              sign="-"
            />
            <Legend
              color={C_RETAINED}
              label="保留图斑"
              count={result.retainedCount}
              area={ha(result.retainedArea)}
            />
            <Text type="secondary" style={NOTE}>
              基于质心 + 冠幅半径的近似匹配; 高精度叠分待后端 GIS。
            </Text>
          </Space>
        )}
      </Card>
    </div>
  );
}

function Legend({
  color,
  label,
  count,
  area,
  sign,
}: {
  color: string;
  label: string;
  count: number;
  area: string;
  sign?: string;
}) {
  const swatch: CSSProperties = { ...SWATCH, background: color };
  return (
    <div style={ROW}>
      <span style={swatch} />
      <div style={ROW_TXT}>
        <div style={ROW_TOP}>
          <span style={ROW_LABEL}>{label}</span>
          <span style={ROW_COUNT}>{count} 株</span>
        </div>
        <span style={ROW_AREA}>
          {sign ?? ""}
          {area} ha
        </span>
      </div>
    </div>
  );
}

const STAGE: CSSProperties = { position: "absolute", inset: 0 };
const PANEL: CSSProperties = {
  position: "absolute",
  right: 16,
  top: 16,
  width: 236,
  zIndex: 6,
  boxShadow: "var(--shadow-2)",
};
const PANEL_BODY: CSSProperties = { paddingTop: 8 };
const CARD_STYLES = { body: PANEL_BODY };
const FULL: CSSProperties = { width: "100%" };
const SUB: CSSProperties = { fontSize: 12 };
const CENTER: CSSProperties = {
  display: "flex",
  justifyContent: "center",
  padding: 16,
};
const ROW: CSSProperties = {
  display: "flex",
  gap: 8,
  alignItems: "flex-start",
};
const SWATCH: CSSProperties = {
  width: 12,
  height: 12,
  borderRadius: 3,
  marginTop: 3,
  flex: "0 0 auto",
  opacity: 0.75,
};
const ROW_TXT: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  flex: 1,
};
const ROW_TOP: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "baseline",
};
const ROW_LABEL: CSSProperties = { fontSize: 13 };
const ROW_COUNT: CSSProperties = {
  fontVariantNumeric: "tabular-nums",
  fontSize: 15,
  fontWeight: 600,
};
const ROW_AREA: CSSProperties = {
  fontSize: 12,
  fontVariantNumeric: "tabular-nums",
  color: "var(--color-text-muted, #5c6b66)",
};
const NOTE: CSSProperties = { fontSize: 11 };
