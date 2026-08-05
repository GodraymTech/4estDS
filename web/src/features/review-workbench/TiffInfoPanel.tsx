import type { CSSProperties } from "react";
import { Collapse, Descriptions, Tag, Typography } from "antd";
import { InfoCircleOutlined } from "@ant-design/icons";
import type { ReviewSession } from "../../entities/review";

const { Text } = Typography;

interface TiffInfoPanelProps {
  session?: ReviewSession;
}

export function TiffInfoPanel({ session }: TiffInfoPanelProps) {
  if (!session) return null;

  const items = [
    { key: "1", label: "文件名", children: <Text copyable>{session.image_name ?? session.tiff_id}</Text> },
    { key: "2", label: "地块", children: `${session.city ?? "—"} / ${session.tract_id ?? "—"}` },
    { key: "3", label: "时相 ID", children: session.phase_id },
    { key: "4", label: "模式", children: <Tag color="blue">{session.mode === "inherit" ? "继承基线" : "从零新启"}</Tag> },
    { key: "5", label: "基线 Run", children: session.base_run_id ? <Text code>{session.base_run_id}</Text> : "无" },
    { key: "6", label: "会话 ID", children: <Text type="secondary" style={{ fontSize: 11 }}>{session.session_id}</Text> },
  ];

  return (
    <Collapse
      ghost
      size="small"
      expandIconPosition="end"
      items={[
        {
          key: "tiff-info",
          label: (
            <Space size={6}>
              <InfoCircleOutlined />
              <Text strong style={{ fontSize: 13 }}>影像与会话元信息</Text>
            </Space>
          ),
          children: (
            <div style={CONTENT}>
              <Descriptions size="small" column={1} bordered items={items} />
            </div>
          ),
        },
      ]}
    />
  );
}

import { Space } from "antd";

const CONTENT: CSSProperties = {
  padding: "4px 0",
};
