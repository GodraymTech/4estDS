import type { CSSProperties, ReactNode } from "react";
import { Alert, Card, Space, Steps, Tag, Typography } from "antd";
import { PageContainer } from "../shared/ui/PageContainer";

const { Text, Paragraph } = Typography;

interface Stage {
  title: string;
  role: string;
  points: string[];
}

// 蓝碳 MRV 流水线(架构预留): 本底 → 监测 → 报告 → 核查 → 签发。
const STAGES: Stage[] = [
  {
    title: "本底核算 · Baseline",
    role: "碳储量基线",
    points: [
      "输入: 地块边界、树种、冠幅/株高(已由检测与分割产出)",
      "方法: 异速生长方程估算地上生物量(AGB) + 根冠比 + 土壤碳密度",
      "输出: 地块碳储量本底(tCO2e)与不确定度区间",
    ],
  },
  {
    title: "监测 · Monitoring (M)",
    role: "增汇/损失",
    points: [
      "复用多时相变化检测: 面积/株数/冠幅Δ → 碳增汇或损失",
      "退化/清除信号联动预警中心, 触发现场复核",
    ],
  },
  {
    title: "报告 · Reporting (R)",
    role: "方法学产出",
    points: [
      "按方法学(CCER 红树林营造林 / VCS VM0033)生成 MRV 报告",
      "复用报告中心模板与导出管线",
    ],
  },
  {
    title: "核查 · Verification (V)",
    role: "证据链",
    points: [
      "第三方核查证据链: 原始影像、推理留痕、版本快照",
      "不可篡改留痕, 支撑第三方审定与核查",
    ],
  },
  {
    title: "签发 · Issuance",
    role: "碳信用",
    points: ["碳信用签发与台账登记, 关联监管台账"],
  },
];

function renderPoints(points: string[]): ReactNode {
  return (
    <ul style={LIST}>
      {points.map((p) => (
        <li key={p}>{p}</li>
      ))}
    </ul>
  );
}

// 蓝碳/MRV: P3 架构占位。按锁定策略不提前实现核算, 不伪造碳量数字。
export function CarbonPage() {
  const items = STAGES.map((s) => ({
    title: (
      <Space size={8} wrap>
        <Text strong>{s.title}</Text>
        <Tag>{s.role}</Tag>
        <Tag color="gold">架构预留</Tag>
      </Space>
    ),
    description: renderPoints(s.points),
  }));

  return (
    <PageContainer
      title="蓝碳 / MRV"
      subtitle="红树林蓝碳本底核算与 MRV(监测-报告-核查)证据链。架构预留, 分阶段落地。"
    >
      <Space direction="vertical" size={16} style={FULL}>
        <Alert
          type="info"
          showIcon
          message="P3 架构占位"
          description="方法学与核算引擎按锁定策略在后续阶段实现; 当前不产出碳量数字, 避免误导决策。"
        />
        <Card size="small" title="MRV 流水线(蓝碳)">
          <Steps direction="vertical" size="small" current={-1} items={items} />
        </Card>
        <Paragraph type="secondary" style={NOTE}>
          说明: 碳核算须遵循选定方法学与本地参数(树种异速方程、土壤碳密度、
          不确定度), 落地前需完成参数标定与第三方方法学确认。
        </Paragraph>
      </Space>
    </PageContainer>
  );
}

const FULL: CSSProperties = { width: "100%" };
const LIST: CSSProperties = { margin: 0, paddingLeft: 18 };
const NOTE: CSSProperties = { marginBottom: 0 };
