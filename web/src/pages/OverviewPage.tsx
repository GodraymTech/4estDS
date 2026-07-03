import type { CSSProperties } from "react";
import { Card, Statistic, Typography, Tag } from "antd";
import { MapStage } from "../shared/ui/MapStage";
import { useTracts } from "../entities/tract";

const { Text } = Typography;

// 总览(驾驶舱 + 一张图): P0 先出全屏地图 + KPI 浮层。
// P1 接入语义缩放(省市县 choropleth → 倒水滴地块 marker → 飞入工作台)。
export function OverviewPage() {
  const { data: tracts, isLoading } = useTracts();
  const count = tracts?.length ?? 0;

  return (
    <div style={STAGE_WRAP}>
      <MapStage center={[113.3, 22.5]} zoom={7} />
      <Card style={PANEL} styles={CARD_STYLES}>
        <Text type="secondary">红树林监管驾驶舱</Text>
        <Statistic title="入库地块" value={count} loading={isLoading} />
        <div style={HINT}>
          <Tag color="processing">P1</Tag>
          <Text type="secondary">
            语义缩放总览图 / 时相卷帘 / 变化检测即将接入
          </Text>
        </div>
      </Card>
    </div>
  );
}

const STAGE_WRAP: CSSProperties = {
  position: "relative",
  flex: 1,
  minHeight: 0,
};
const PANEL: CSSProperties = {
  position: "absolute",
  top: 16,
  left: 16,
  width: 260,
  boxShadow: "var(--shadow-2)",
};
const PANEL_BODY: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 8,
};
const CARD_STYLES = { body: PANEL_BODY };
const HINT: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  marginTop: 4,
};
