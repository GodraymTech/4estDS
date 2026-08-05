import type { CSSProperties } from "react";
import { Space, Typography } from "antd";
import { CheckOutlined, LoadingOutlined } from "@ant-design/icons";
import { useReviewWorkbenchStore } from "./store";

const { Text } = Typography;

interface StatusBarProps {
  totalItems: number;
  visibleItems: number;
}

export function StatusBar({ totalItems, visibleItems }: StatusBarProps) {
  const selectedCount = useReviewWorkbenchStore((s) => s.selectedIds.length);
  const zoom = useReviewWorkbenchStore((s) => s.zoom);
  const isSyncing = useReviewWorkbenchStore((s) => s.isSyncing);

  return (
    <div style={CONTAINER}>
      {/* 左区 */}
      <Space size={16}>
        <Text type="secondary" style={FONT}>
          工作集对象: <strong>{totalItems}</strong>
        </Text>
        <Text type="secondary" style={FONT}>
          当前显示: <strong>{visibleItems}</strong>
        </Text>
        <Text type="secondary" style={FONT}>
          已选择: <strong>{selectedCount}</strong>
        </Text>
      </Space>

      {/* 中区：草稿同步状态 */}
      <div>
        {isSyncing ? (
          <Text style={{ ...FONT, color: "#faad14" }}>
            <LoadingOutlined spin /> 正在同步草稿至服务端...
          </Text>
        ) : (
          <Text style={{ ...FONT, color: "#52c41a" }}>
            <CheckOutlined /> 草稿已实时同步
          </Text>
        )}
      </div>

      {/* 右区：缩放信息 */}
      <Space size={12}>
        <Text type="secondary" style={FONT}>
          视图缩放: {Math.round(zoom * 100)}%
        </Text>
      </Space>
    </div>
  );
}

const CONTAINER: CSSProperties = {
  height: 24,
  paddingInline: 12,
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  borderTop: "1px solid var(--border-color, rgba(125, 125, 125, 0.15))",
  backgroundColor: "var(--bg-statusbar, rgba(0, 0, 0, 0.25))",
};

const FONT: CSSProperties = {
  fontSize: 12,
};
