import type { CSSProperties, ReactNode } from "react";
import { Alert, Card, Space, Steps, Tag, Typography } from "antd";
import { PageContainer } from "../shared/ui/PageContainer";

const { Text, Paragraph } = Typography;

interface Stage {
  title: string;
  role: string;
  points: string[];
}

// 互花米草(Spartina alterniflora)入侵专项: 分类器→制图→预警→治理成效。
const STAGES: Stage[] = [
  {
    title: "专项分类器 · Classifier",
    role: "多类地物",
    points: [
      "在检测/分割基础上新增“互花米草”类别(多光谱/纹理/物候特征)",
      "区分红树林 / 互花米草 / 光滩 / 水体",
      "需专项标注数据与迁移学习, 降低与红树林混淆",
    ],
  },
  {
    title: "入侵制图 · Mapping",
    role: "范围/速率",
    points: [
      "多时相入侵范围与扩散速率, 识别入侵前沿",
      "复用逐图斑变化检测与量算能力",
    ],
  },
  {
    title: "预警联动 · Alerting",
    role: "入侵种",
    points: [
      "入侵斑块 → 预警中心新增“入侵种”类别, 分级派单",
      "与退化/清除信号同台管理",
    ],
  },
  {
    title: "治理成效 · Restoration",
    role: "除治核验",
    points: ["除治后复绿/复红树林监测, 成效核验", "与监管台账、报告中心打通"],
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

// 入侵种监测(互花米草专项): P3 架构占位, 需专项训练数据与地面验证。
export function InvasionPage() {
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
      title="入侵种监测"
      subtitle="互花米草入侵专项: 分类器-制图-预警-治理成效。架构预留, 分阶段落地。"
    >
      <Space direction="vertical" size={16} style={FULL}>
        <Alert
          type="info"
          showIcon
          message="P3 架构占位"
          description="互花米草专项分类器需单独标注数据与地面验证; 当前仅展示专项技术路线, 不产出推理结果。"
        />
        <Card size="small" title="互花米草入侵专项流水线">
          <Steps direction="vertical" size="small" current={-1} items={items} />
        </Card>
        <Paragraph type="secondary" style={NOTE}>
          说明: 互花米草与红树林光谱相近, 需多光谱/物候/纹理多特征与实地样方
          标定; 建议与当地海洋/林业部门共建标注集。
        </Paragraph>
      </Space>
    </PageContainer>
  );
}

const FULL: CSSProperties = { width: "100%" };
const LIST: CSSProperties = { margin: 0, paddingLeft: 18 };
const NOTE: CSSProperties = { marginBottom: 0 };
