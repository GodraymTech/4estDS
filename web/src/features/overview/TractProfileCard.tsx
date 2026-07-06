import type { CSSProperties, ReactNode } from "react";
import { Tag, Typography } from "antd";
import type { Tract } from "../../entities/tract";

const { Text } = Typography;

// 地块 profile 悬停卡: 固定定位在标记上方(视口坐标), 不拦截鼠标。
export function TractProfileCard({
  tract,
  x,
  y,
}: {
  tract: Tract;
  x: number;
  y: number;
}) {
  const style: CSSProperties = { ...CARD, left: x, top: y };
  return (
    <div style={style}>
      <div style={TITLE}>{tract.name || tract.tract_id}</div>
      <Row label="地点" value={tract.location || "-"} />
      <Row label="时相" value={tract.acquisition_time || "-"} />
      <Row label="面积" value={formatArea(tract)} mono />
      <div style={FOOT}>
        {tract.active_run_id ? (
          <Tag color="green">已发布</Tag>
        ) : (
          <Tag>未发布</Tag>
        )}
        <Text type="secondary" style={HINT}>
          点击进入工作台 →
        </Text>
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  mono,
}: {
  label: string;
  value: ReactNode;
  mono?: boolean;
}) {
  return (
    <div style={ROW}>
      <span style={ROW_LABEL}>{label}</span>
      <span style={mono ? ROW_VALUE_MONO : ROW_VALUE}>{value}</span>
    </div>
  );
}

function formatArea(t: Tract): string {
  if (typeof t.geo_area !== "number") return "-";
  return t.geo_area.toLocaleString() + " " + (t.area_unit || "");
}

const CARD: CSSProperties = {
  position: "fixed",
  transform: "translate(-50%, calc(-100% - 14px))",
  zIndex: 1000,
  pointerEvents: "none",
  width: 220,
  background: "var(--color-surface)",
  borderRadius: 10,
  border: "1px solid var(--color-border, #d8e0dd)",
  boxShadow: "var(--shadow-2)",
  padding: "10px 12px",
  fontSize: 12,
  color: "var(--color-text)",
};
const TITLE: CSSProperties = {
  fontWeight: 600,
  color: "var(--color-text, #10302b)",
  marginBottom: 6,
  fontSize: 13,
};
const ROW: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 12,
  lineHeight: "20px",
};
const ROW_LABEL: CSSProperties = { color: "var(--color-text-muted, #5c6b66)" };
const ROW_VALUE: CSSProperties = {
  color: "var(--color-text, #10302b)",
  textAlign: "right",
};
const ROW_VALUE_MONO: CSSProperties = {
  ...ROW_VALUE,
  fontVariantNumeric: "tabular-nums",
};
const FOOT: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  marginTop: 8,
};
const HINT: CSSProperties = { fontSize: 11 };
