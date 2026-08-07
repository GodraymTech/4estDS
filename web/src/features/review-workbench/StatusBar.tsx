import { Space, Typography } from "antd";
import { CheckOutlined, LoadingOutlined } from "@ant-design/icons";
import { useReviewWorkbenchStore } from "./store";

const { Text } = Typography;

export function StatusBar({ totalItems, visibleItems }: { totalItems: number; visibleItems: number }) {
  const selectedCount = useReviewWorkbenchStore((state) => state.selectedIds.length);
  const zoom = useReviewWorkbenchStore((state) => state.zoom);
  const isSyncing = useReviewWorkbenchStore((state) => state.isSyncing);
  return (
    <div className="review-statusbar">
      <Space size={16}><Text type="secondary">对象 <strong>{totalItems}</strong></Text><Text type="secondary">显示 <strong>{visibleItems}</strong></Text><Text type="secondary">已选 <strong>{selectedCount}</strong></Text></Space>
      <Text className={isSyncing ? "is-syncing" : "is-synced"}>{isSyncing ? <><LoadingOutlined spin /> 正在同步草稿</> : <><CheckOutlined /> 草稿已同步</>}</Text>
      <Text type="secondary">地图缩放 {zoom.toFixed(1)}</Text>
    </div>
  );
}
