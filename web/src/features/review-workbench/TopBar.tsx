import type { CSSProperties } from "react";
import { Button, Popconfirm, Space, Tag, Typography } from "antd";
import { ArrowLeftOutlined, UndoOutlined, RedoOutlined, CheckOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import type { ReviewSession } from "../../entities/review";
import { ConnectionStatus } from "../../shared/ui/ConnectionStatus";

const { Text } = Typography;

interface TopBarProps {
  session?: ReviewSession;
  canUndo?: boolean;
  canRedo?: boolean;
  onUndo?: () => void;
  onRedo?: () => void;
  onPublish?: () => void;
  isPublishing?: boolean;
}

export function TopBar({
  session,
  canUndo = false,
  canRedo = false,
  onUndo,
  onRedo,
  onPublish,
  isPublishing = false,
}: TopBarProps) {
  const navigate = useNavigate();

  const title = session
    ? `${session.city ?? "地块"} · ${session.tract_id ?? session.tiff_id} (${session.phase_id})`
    : "单 TIFF 智能复核";

  return (
    <div style={CONTAINER}>
      {/* 左侧：返回与会话信息 */}
      <Space size={12}>
        <Button
          type="text"
          icon={<ArrowLeftOutlined style={{ fontSize: 16 }} />}
          onClick={() => navigate("/review")}
          aria-label="返回"
        />
        <Text strong style={{ fontSize: 16 }}>{title}</Text>
        {session && (
          <>
            <Tag color={session.mode === "inherit" ? "blue" : "purple"}>
              {session.mode === "inherit" ? "继承模式" : "新启模式"}
            </Tag>
            <Tag color={session.status === "active" ? "processing" : "success"}>
              {session.status === "active" ? "复核中" : "已发布"}
            </Tag>
          </>
        )}
      </Space>

      {/* 右侧：操作区 */}
      <Space size={12}>
        <Space.Compact>
          <Button
            type="text"
            icon={<UndoOutlined />}
            disabled={!canUndo}
            onClick={onUndo}
            title="撤销 (Ctrl+Z)"
          />
          <Button
            type="text"
            icon={<RedoOutlined />}
            disabled={!canRedo}
            onClick={onRedo}
            title="重做 (Ctrl+Y)"
          />
        </Space.Compact>

        <ConnectionStatus />

        {session?.status === "active" && (
          <Popconfirm
            title="发布复核结果"
            description="发布后将生成 review run 并原子替换该 TIFF 的正式结果。确认发布？"
            onConfirm={onPublish}
            okText="确认发布"
            cancelText="取消"
          >
            <Button
              type="primary"
              icon={<CheckOutlined />}
              loading={isPublishing}
              style={{ backgroundColor: "#0e6e63", borderColor: "#0e6e63" }}
            >
              发布结果
            </Button>
          </Popconfirm>
        )}
      </Space>
    </div>
  );
}

const CONTAINER: CSSProperties = {
  height: 48,
  paddingInline: 16,
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  borderBottom: "1px solid var(--border-color, rgba(125, 125, 125, 0.2))",
  backgroundColor: "var(--bg-topbar, rgba(0, 0, 0, 0.2))",
};
