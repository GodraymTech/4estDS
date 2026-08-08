import type { CSSProperties } from "react";
import { Card, Descriptions, Space, Tag, Typography } from "antd";
import { FileImageOutlined, GlobalOutlined } from "@ant-design/icons";
import type { ReviewMapContext, ReviewSession } from "../../shared/api";

const { Text } = Typography;

interface TiffInfoPanelProps {
  session?: ReviewSession;
  mapContext?: ReviewMapContext;
}

export function TiffInfoPanel({ session, mapContext }: TiffInfoPanelProps) {
  if (!session) return null;

  const basicItems = [
    { key: "tiff_id", label: "TIFF ID", children: <Text code strong>{session.tiff_id}</Text> },
    { key: "image_name", label: "文件名", children: <Text copyable style={{ fontSize: 12 }}>{session.image_name ?? session.tiff_id}</Text> },
    { key: "location", label: "行政区划 / 地块", children: `${session.city ?? "—"} / ${session.tract_id ?? "—"}` },
    { key: "phase_id", label: "时相编号", children: <Text copyable>{session.phase_id}</Text> },
    { key: "mode", label: "复核工作模式", children: <Tag color="blue">{session.mode === "inherit" ? "继承存量基线" : "从零新启标注"}</Tag> },
    { key: "base_run", label: "基准 Run ID", children: session.base_run_id ? <Text code>{session.base_run_id}</Text> : "—" },
    { key: "session_id", label: "当前会话 ID", children: <Text type="secondary" copyable style={{ fontSize: 11 }}>{session.session_id}</Text> },
  ];

  const rasterItems = mapContext ? [
    {
      key: "dim",
      label: "像素尺寸 (W × H)",
      children: (
        <Text strong style={{ fontVariantNumeric: "tabular-nums" }}>
          {mapContext.pixel_width.toLocaleString()} × {mapContext.pixel_height.toLocaleString()} px
        </Text>
      ),
    },
    {
      key: "gsd",
      label: "地面分辨率 (GSD)",
      children: (
        <Tag color="cyan" style={{ fontVariantNumeric: "tabular-nums", fontWeight: 600 }}>
          {(mapContext.gsd * 100).toFixed(1)} cm / 像素 ({mapContext.gsd.toFixed(3)} m/px)
        </Tag>
      ),
    },
    {
      key: "bbox",
      label: "WGS84 经纬度四至",
      children: (
        <div style={{ fontSize: 11, fontVariantNumeric: "tabular-nums", color: "var(--review-muted)" }}>
          <div>西: {mapContext.bounds_wgs84[0].toFixed(6)}° / 南: {mapContext.bounds_wgs84[1].toFixed(6)}°</div>
          <div>东: {mapContext.bounds_wgs84[2].toFixed(6)}° / 北: {mapContext.bounds_wgs84[3].toFixed(6)}°</div>
        </div>
      ),
    },
    {
      key: "corners",
      label: "角点坐标投影",
      children: (
        <Text type="secondary" style={{ fontSize: 11 }}>
          已完成 WGS84 仿射变换与像素正反算校准
        </Text>
      ),
    },
  ] : [];

  return (
    <div style={CONTAINER}>
      {/* 影像基础元数据 */}
      <Card size="small" title={<Space size={6}><FileImageOutlined style={{ color: "#5e9fe8" }} /><Text strong style={{ fontSize: 12 }}>正射遥感影像元信息</Text></Space>} style={CARD}>
        <Descriptions size="small" column={1} bordered items={basicItems} labelStyle={LABEL} contentStyle={CONTENT} />
      </Card>

      {/* 遥感与空间物理指标 */}
      {mapContext ? (
        <Card size="small" title={<Space size={6}><GlobalOutlined style={{ color: "#52c99a" }} /><Text strong style={{ fontSize: 12 }}>遥感物理与空间参数</Text></Space>} style={CARD}>
          <Descriptions size="small" column={1} bordered items={rasterItems} labelStyle={LABEL} contentStyle={CONTENT} />
        </Card>
      ) : null}
    </div>
  );
}

const CONTAINER: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 12,
  padding: "10px",
  overflowY: "auto",
  height: "100%",
};

const CARD: CSSProperties = {
  background: "transparent",
  borderColor: "var(--review-border, rgba(125, 125, 125, 0.2))",
};

const LABEL: CSSProperties = {
  width: "110px",
  fontSize: "11px",
  color: "var(--review-muted)",
  padding: "6px 8px",
};

const CONTENT: CSSProperties = {
  fontSize: "12px",
  padding: "6px 8px",
};
