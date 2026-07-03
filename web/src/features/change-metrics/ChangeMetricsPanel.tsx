import { useMemo } from "react";
import type { CSSProperties, ReactNode } from "react";
import { Card, Spin, Tag } from "antd";
import type { Phase } from "../../entities/phase";
import { useObservations } from "../../entities/observation";
import { buildChangeMetrics, toHectares } from "./metrics";

const UP = "#3e8e5a"; // 扩张(好)
const DOWN = "#b8472a"; // 退化(警示)

// 变化量化面板: 与时相卷帘共用受控 range;
// 本面板自行拉取两期树冠观测(React Query 按 queryKey 去重, 不会重复请求)。
export function ChangeMetricsPanel({
  phases,
  range,
}: {
  phases: Phase[];
  range: [number, number];
}) {
  const before = phases[range[0]];
  const after = phases[range[1]];
  const beforeObs = useObservations(before?.id, "crown");
  const afterObs = useObservations(after?.id, "crown");
  const loading = beforeObs.isFetching || afterObs.isFetching;

  const m = useMemo(
    () => buildChangeMetrics(beforeObs.data, afterObs.data),
    [beforeObs.data, afterObs.data],
  );

  const single = range[0] === range[1];

  return (
    <Card style={PANEL} styles={CARD_STYLES} title="变化量化">
      {single ? (
        <div style={HINT}>选择两个不同时相以对比。</div>
      ) : loading ? (
        <div style={CENTER}>
          <Spin size="small" />
        </div>
      ) : (
        <div style={GRID}>
          <Metric
            label="冠层株数"
            before={String(m.countBefore)}
            after={String(m.countAfter)}
            delta={m.countDelta}
            pct={m.countPct}
            unit="株"
          />
          <Metric
            label="冠幅面积"
            before={toHectares(m.areaBefore).toLocaleString()}
            after={toHectares(m.areaAfter).toLocaleString()}
            delta={m.areaDelta}
            pct={m.areaPct}
            unit="ha"
            deltaText={toHectares(Math.abs(m.areaDelta)).toLocaleString()}
          />
          <div style={FOOT}>
            <Tag color={m.areaDelta >= 0 ? "green" : "red"}>
              {m.areaDelta >= 0 ? "冠幅扩张" : "冠幅退化"}
            </Tag>
            <span style={NOTE}>聚合总量对比（逐图斑见「图斑变化」）</span>
          </div>
        </div>
      )}
    </Card>
  );
}

function Metric({
  label,
  before,
  after,
  delta,
  pct,
  unit,
  deltaText,
}: {
  label: string;
  before: string;
  after: string;
  delta: number;
  pct: number | null;
  unit: string;
  deltaText?: string;
}): ReactNode {
  const color = delta >= 0 ? UP : DOWN;
  const sign = delta >= 0 ? "+" : "-";
  const shown = deltaText ?? String(Math.abs(delta));
  const deltaStyle: CSSProperties = { ...DELTA, color };
  return (
    <div style={METRIC}>
      <div style={METRIC_LABEL}>{label}</div>
      <div style={METRIC_ROW}>
        <span style={MONO}>{before}</span>
        <span style={ARROW}>→</span>
        <span style={MONO}>{after}</span>
        <span style={UNIT}>{unit}</span>
      </div>
      <div style={deltaStyle}>
        {sign}
        {shown} {unit}
        {pct === null ? "" : "（" + sign + Math.abs(pct).toFixed(1) + "%）"}
      </div>
    </div>
  );
}

const PANEL: CSSProperties = {
  position: "absolute",
  left: 16,
  bottom: 16,
  width: 260,
  zIndex: 6,
  boxShadow: "var(--shadow-2)",
};
const PANEL_BODY: CSSProperties = { paddingTop: 8 };
const CARD_STYLES = { body: PANEL_BODY };
const GRID: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 12,
};
const METRIC: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 2,
};
const METRIC_LABEL: CSSProperties = {
  fontSize: 12,
  color: "var(--color-text-muted, #5c6b66)",
};
const METRIC_ROW: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  gap: 6,
};
const MONO: CSSProperties = {
  fontVariantNumeric: "tabular-nums",
  fontSize: 16,
  fontWeight: 600,
};
const ARROW: CSSProperties = { color: "var(--color-text-muted, #5c6b66)" };
const UNIT: CSSProperties = {
  fontSize: 12,
  color: "var(--color-text-muted, #5c6b66)",
};
const DELTA: CSSProperties = {
  fontSize: 12,
  fontVariantNumeric: "tabular-nums",
};
const FOOT: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
  marginTop: 2,
};
const NOTE: CSSProperties = {
  fontSize: 11,
  color: "var(--color-text-muted, #5c6b66)",
};
const HINT: CSSProperties = {
  fontSize: 12,
  color: "var(--color-text-muted, #5c6b66)",
};
const CENTER: CSSProperties = {
  display: "flex",
  justifyContent: "center",
  padding: 16,
};
