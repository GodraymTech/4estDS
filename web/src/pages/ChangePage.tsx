import { useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { Card, Empty, Select, Space, Spin, Tag, Typography } from "antd";
import { useTracts } from "../entities/tract";
import { groupPhasesByLocation } from "../entities/phase";
import { TemporalCompare } from "../features/temporal-wipe";

const { Text } = Typography;

// 变化检测: 时相卷帘对比两期; 单一时相自动降级为现状展示。
export function ChangePage() {
  const { data: tracts, isLoading } = useTracts();
  const groups = useMemo(() => groupPhasesByLocation(tracts ?? []), [tracts]);
  const [location, setLocation] = useState<string | undefined>(undefined);

  const active = useMemo(() => {
    if (groups.length === 0) return undefined;
    return groups.find((g) => g.location === location) ?? groups[0];
  }, [groups, location]);

  const options = groups.map((g) => ({
    value: g.location,
    label: g.location + "\uff08" + g.phases.length + " \u65f6相\uff09",
  }));

  return (
    <div style={STAGE_WRAP}>
      {isLoading ? (
        <div style={CENTER}>
          <Spin />
        </div>
      ) : active ? (
        <TemporalCompare
          key={active.location}
          phases={active.phases}
          center={[110.3, 21.5]}
          zoom={11}
        />
      ) : (
        <div style={CENTER}>
          <Empty description="暂无地块数据" />
        </div>
      )}

      <Card style={PANEL} styles={CARD_STYLES} title="变化检测">
        <Space direction="vertical" size={8} style={FULL}>
          <Text type="secondary">选择地点，拖动分隔把手卷帘对比两期。</Text>
          <Select
            style={FULL}
            placeholder="选择地点"
            value={active?.location}
            options={options}
            onChange={setLocation}
            disabled={groups.length === 0}
          />
          <Space size={4} wrap>
            <Tag color="gold">旧时相</Tag>
            <Tag color="green">新时相</Tag>
            <Tag>P2 接入多时相真影像</Tag>
          </Space>
        </Space>
      </Card>
    </div>
  );
}

const STAGE_WRAP: CSSProperties = {
  position: "relative",
  flex: 1,
  minHeight: 0,
};
const CENTER: CSSProperties = {
  position: "absolute",
  inset: 0,
  display: "flex",
  justifyContent: "center",
  alignItems: "center",
};
const PANEL: CSSProperties = {
  position: "absolute",
  top: 16,
  left: 16,
  width: 300,
  zIndex: 6,
  boxShadow: "var(--shadow-2)",
};
const PANEL_BODY: CSSProperties = { paddingTop: 4 };
const CARD_STYLES = { body: PANEL_BODY };
const FULL: CSSProperties = { width: "100%" };
