import type { CSSProperties } from "react";
import { Card, Col, Row, Statistic } from "antd";
import { useTracts } from "../../entities/tract";

// 数据看板: 一张图的互补视图(驾驶舱 KPI 概览)。
export function DashboardPanel() {
  const { data: tracts, isLoading } = useTracts();
  const list = tracts ?? [];
  const total = list.length;
  const published = list.filter((t) => t.active_run_id).length;
  const area = list.reduce((s, t) => s + (t.geo_area ?? 0), 0);
  const phases = new Set(list.map((t) => t.phase_id).filter(Boolean))
    .size;
  const unit = list.find((t) => t.area_unit)?.area_unit || "";

  const cards = [
    { title: "入库地块", value: total, suffix: "" },
    { title: "已发布", value: published, suffix: "" },
    { title: "监测总面积", value: Math.round(area), suffix: unit },
    { title: "时相覆盖", value: phases, suffix: "期" },
  ];

  return (
    <div style={WRAP}>
      <Row gutter={[16, 16]}>
        {cards.map((c) => (
          <Col key={c.title} xs={12} md={6}>
            <Card>
              <Statistic
                title={c.title}
                value={c.value}
                suffix={c.suffix}
                loading={isLoading}
              />
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  );
}

const WRAP: CSSProperties = { padding: 24, overflow: "auto", flex: 1 };
