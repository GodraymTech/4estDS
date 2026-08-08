import type { CSSProperties } from "react";
import { Button, Popconfirm, Space, Tag, Tooltip, Typography } from "antd";
import { ArrowLeftOutlined, MoonOutlined, SendOutlined, SunOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import type { ReviewSession } from "../../entities/review";
import { ConnectionStatus } from "../../shared/ui/ConnectionStatus";
import { useAppTheme } from "../../app/providers";

const { Text } = Typography;

export function TopBar({ session, onPublish, isPublishing = false }: {
  session?: ReviewSession;
  onPublish?: () => void;
  isPublishing?: boolean;
}) {
  const navigate = useNavigate();
  const { dark, toggleMode } = useAppTheme();
  const title = session ? `${session.image_name ?? session.tiff_id} · ${formatPhase(session.phase_id)}` : "单 TIFF 智能复核";

  return (
    <div style={CONTAINER}>
      <Space size={12}>
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate("/review")} aria-label="返回智能复核" />
        <Text strong style={{ fontSize: 16 }}>{title}</Text>
        {session ? (
          <>
            <Tag color={session.mode === "inherit" ? "blue" : "purple"}>{session.mode === "inherit" ? "继承模式" : "新启模式"}</Tag>
            <Tag color={session.status === "active" ? "processing" : "success"}>{session.status === "active" ? "复核中" : "已发布"}</Tag>
          </>
        ) : null}
      </Space>
      <Space size={12}>
        <ConnectionStatus />
        <Tooltip title={dark ? "切换为明亮模式" : "切换为暗黑模式"}>
          <Button
            type="text"
            icon={dark ? <SunOutlined /> : <MoonOutlined />}
            onClick={toggleMode}
            aria-label="切换亮暗主题"
          />
        </Tooltip>
        {session?.status === "active" ? (
          <Popconfirm title="发布复核结果" description="发布后将生成 review run，并原子替换该 TIFF 的正式结果。" onConfirm={onPublish} okText="确认发布" cancelText="取消">
            <Button type="primary" icon={<SendOutlined />} loading={isPublishing}>发布结果</Button>
          </Popconfirm>
        ) : null}
      </Space>
    </div>
  );
}

function formatPhase(value: string) {
  return /^\d{8}$/.test(value) ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}` : value;
}

const CONTAINER: CSSProperties = {
  height: 48,
  paddingInline: 16,
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  borderBottom: "1px solid var(--border-color, rgba(125, 125, 125, 0.2))",
  backgroundColor: "var(--bg-topbar)",
};
