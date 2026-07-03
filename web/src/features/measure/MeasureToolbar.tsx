import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { Button, Card, Segmented, Space, Typography } from "antd";
import type { LngLat, MapController } from "../../shared/map-core";
import {
  buildAreaGeoJson,
  buildLineGeoJson,
  buildPointsGeoJson,
  computeMeasure,
  formatArea,
  formatLength,
  type MeasureMode,
} from "./measureModel";

const { Text } = Typography;

const LAYER_PTS = "measure-pts";
const LAYER_LINE = "measure-line";
const LAYER_FILL = "measure-fill";
const C_LINE = "#b8472a";
const C_FILL = "#c9a24b";
const C_PT = "#10302b";

// 图层量算: 地图上量距离/面积(测地)。点击加点, 实时图形 + 读数。
// 仅在激活时订阅地图点击并切换十字光标; 关闭时退订并清图层(不影响普通交互)。
export function MeasureToolbar({ map }: { map: MapController | null }) {
  const [mode, setMode] = useState<MeasureMode>("idle");
  const [coords, setCoords] = useState<LngLat[]>([]);

  // 点击取点(仅激活时)。
  useEffect(() => {
    if (!map || mode === "idle") return;
    map.setCursor("crosshair");
    const off = map.on("mapClick", (p) => {
      setCoords((prev) => [...prev, p as LngLat]);
    });
    return () => {
      off();
      map.setCursor(null);
    };
  }, [map, mode]);

  // 同步量算图层(点/线/面)。
  useEffect(() => {
    if (!map || !map.isReady()) return;
    if (mode === "idle") {
      map.removeLayer(LAYER_FILL);
      map.removeLayer(LAYER_LINE);
      map.removeLayer(LAYER_PTS);
      return;
    }
    if (mode === "area") {
      map.setGeoJsonLayer({
        id: LAYER_FILL,
        kind: "polygon",
        data: buildAreaGeoJson(coords),
        color: C_FILL,
      });
    } else {
      map.removeLayer(LAYER_FILL);
    }
    map.setGeoJsonLayer({
      id: LAYER_LINE,
      kind: "line",
      data: buildLineGeoJson(coords),
      color: C_LINE,
    });
    map.setGeoJsonLayer({
      id: LAYER_PTS,
      kind: "point",
      data: buildPointsGeoJson(coords),
      color: C_PT,
    });
  }, [map, mode, coords]);

  const result = useMemo(() => computeMeasure(mode, coords), [mode, coords]);

  const changeMode = (m: MeasureMode) => {
    setMode(m);
    setCoords([]);
  };
  const undo = () => setCoords((p) => p.slice(0, -1));
  const clear = () => setCoords([]);

  const options = [
    { label: "关闭", value: "idle" },
    { label: "量距离", value: "distance" },
    { label: "量面积", value: "area" },
  ];

  return (
    <Card style={PANEL} styles={CARD_STYLES}>
      <Space direction="vertical" size={8} style={FULL}>
        <Segmented
          size="small"
          value={mode}
          options={options}
          onChange={(v) => changeMode(v as MeasureMode)}
          block
        />
        {mode === "idle" ? (
          <Text type="secondary" style={SUB}>
            选择量距离或量面积后点击地图
          </Text>
        ) : (
          <>
            <Space size={4}>
              <Button
                size="small"
                onClick={undo}
                disabled={coords.length === 0}
              >
                撤销
              </Button>
              <Button
                size="small"
                onClick={clear}
                disabled={coords.length === 0}
              >
                清除
              </Button>
            </Space>
            <div style={READOUT}>
              {mode === "distance" ? (
                <Text style={METRIC}>长度 {formatLength(result.length)}</Text>
              ) : (
                <>
                  <Text style={METRIC}>面积 {formatArea(result.area)}</Text>
                  <Text type="secondary" style={SUB}>
                    周长 {formatLength(result.length)}
                  </Text>
                </>
              )}
              <Text type="secondary" style={SUB}>
                {result.points} 个点 · 点击地图加点
              </Text>
            </div>
          </>
        )}
      </Space>
    </Card>
  );
}

const PANEL: CSSProperties = {
  position: "absolute",
  bottom: 24,
  left: 16,
  width: 220,
  zIndex: 6,
  boxShadow: "var(--shadow-2)",
};
const CARD_BODY: CSSProperties = { padding: 12 };
const CARD_STYLES = { body: CARD_BODY };
const FULL: CSSProperties = { width: "100%" };
const READOUT: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 2,
};
const METRIC: CSSProperties = {
  fontFamily: "var(--font-display)",
  fontVariantNumeric: "tabular-nums",
  fontSize: 15,
  color: "#10302b",
};
const SUB: CSSProperties = { fontSize: 12 };
