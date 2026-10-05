import { useState } from "react";
import type { CSSProperties } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Drawer, Popconfirm, Skeleton, Space, Tag, Typography, message } from "antd";
import {
  CheckCircleFilled,
  CloseCircleFilled,
  FormOutlined,
  LoadingOutlined,
  ReloadOutlined,
  UndoOutlined,
} from "@ant-design/icons";
import { endpoints } from "../../shared/api/endpoints";
import { useAppTheme } from "../../app/providers";
import { BlackboardEditor } from "./BlackboardEditor";

const { Text } = Typography;

interface BlackboardDrawerProps {
  open: boolean;
  onClose: () => void;
}

export function BlackboardDrawer({ open, onClose }: BlackboardDrawerProps) {
  const { dark } = useAppTheme();
  const queryClient = useQueryClient();
  const [syncStatus, setSyncStatus] = useState<"idle" | "saving" | "saved" | "error">("saved");
  const [lastSaved, setLastSaved] = useState<string>("");
  const [resetKey, setResetKey] = useState(0);

  const { data: note, isLoading, isError, refetch } = useQuery({
    queryKey: ["blackboard", "default"],
    queryFn: () => endpoints.getBlackboardNote("default"),
    enabled: open,
    staleTime: 1000 * 15,
  });

  const handleReset = async () => {
    try {
      setSyncStatus("saving");
      await endpoints.resetBlackboardNote("default");
      message.success("小黑板已重置为初始模板");
      await queryClient.invalidateQueries({ queryKey: ["blackboard", "default"] });
      setResetKey((prev) => prev + 1);
      setSyncStatus("saved");
    } catch {
      message.error("重置失败");
      setSyncStatus("error");
    }
  };

  const drawerBg = dark ? "#151d1a" : "#fafcfa";
  const drawerBorder = dark ? "#24322d" : "#e6ece8";

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={640}
      destroyOnClose={false}
      styles={{
        header: {
          background: drawerBg,
          borderBottom: `1px solid ${drawerBorder}`,
          padding: "14px 20px",
        },
        body: {
          background: drawerBg,
          padding: "16px 20px",
          overflowY: "auto",
        },
        footer: {
          background: drawerBg,
          borderTop: `1px solid ${drawerBorder}`,
          padding: "10px 20px",
        },
      }}
      title={
        <div style={HEADER_CONTAINER}>
          <div style={TITLE_GROUP}>
            <FormOutlined style={{ color: "#34d399", fontSize: 18 }} />
            <Text strong style={{ fontSize: 16, color: dark ? "#ecfdf5" : "#064e3b" }}>
              公共备忘小黑板
            </Text>
            <Tag color="cyan" style={{ borderRadius: 12, marginInlineStart: 4, fontSize: 11 }}>
              全员共享 · Notion 块级
            </Tag>
          </div>
          <Space size={12}>
            {syncStatus === "saving" && (
              <Space size={4}>
                <LoadingOutlined style={{ color: "#1890ff", fontSize: 13 }} />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  同步中...
                </Text>
              </Space>
            )}
            {syncStatus === "saved" && (
              <Space size={4}>
                <CheckCircleFilled style={{ color: "#52c41a", fontSize: 13 }} />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  已同步云端 {lastSaved ? `(${lastSaved})` : ""}
                </Text>
              </Space>
            )}
            {syncStatus === "error" && (
              <Space size={4}>
                <CloseCircleFilled style={{ color: "#ff4d4f", fontSize: 13 }} />
                <Text type="danger" style={{ fontSize: 12 }}>
                  同步失败
                </Text>
              </Space>
            )}

            <Popconfirm
              title="确定要重置公共小黑板吗？"
              description="重置后当前黑板所有内容将被恢复为系统默认模板。"
              onConfirm={handleReset}
              okText="确认重置"
              cancelText="取消"
              okButtonProps={{ danger: true }}
            >
              <Button size="small" type="text" icon={<UndoOutlined />} style={RESET_BTN}>
                重置
              </Button>
            </Popconfirm>
          </Space>
        </div>
      }
      footer={
        <div style={FOOTER_WRAP}>
          <Text type="secondary" style={{ fontSize: 12, color: dark ? "#7b948a" : "#6b7280" }}>
            💡 快捷提示：在空白行输入 <code>/</code> 即可呼出全套排版与待办组件；任何团队成员皆可随时修改，改动自动秒级同步。
          </Text>
        </div>
      }
    >
      {isLoading && (
        <div style={{ padding: "20px 8px" }}>
          <Skeleton active paragraph={{ rows: 8 }} />
        </div>
      )}

      {isError && (
        <Alert
          type="error"
          message="无法加载公共备忘录"
          description={
            <Space direction="vertical" size={8} style={{ marginTop: 8 }}>
              <span>请检查后端服务连接是否正常。</span>
              <Button size="small" icon={<ReloadOutlined />} onClick={() => refetch()}>
                重试加载
              </Button>
            </Space>
          }
          showIcon
        />
      )}

      {!isLoading && !isError && note && (
        <BlackboardEditor
          key={`${note.note_id}_${note.updated_at}_${resetKey}`}
          note={note}
          onSyncStatusChange={(status, lastTime) => {
            setSyncStatus(status);
            if (lastTime) setLastSaved(lastTime);
          }}
        />
      )}
    </Drawer>
  );
}

const HEADER_CONTAINER: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  width: "100%",
};

const TITLE_GROUP: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
};

const RESET_BTN: CSSProperties = {
  fontSize: 12,
  color: "#94a3b8",
};

const FOOTER_WRAP: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
};
