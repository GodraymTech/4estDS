import { Space, Typography } from "antd";
import { useReviewWorkbenchStore } from "./store";

const { Text } = Typography;

export function StatusBar({ totalItems, visibleItems }: { totalItems: number; visibleItems: number }) {
  const selectedCount = useReviewWorkbenchStore((state) => state.selectedIds.length);
  const zoom = useReviewWorkbenchStore((state) => state.zoom);

  return (
    <div className="review-statusbar">
      <Space size={16}>
        <Text type="secondary">对象总计 <strong>{totalItems}</strong></Text>
        <Text type="secondary">当前显示 <strong>{visibleItems}</strong></Text>
        <Text type="secondary">已选中 <strong>{selectedCount}</strong></Text>
      </Space>
      <Text type="secondary">地图缩放 {zoom.toFixed(1)}</Text>
    </div>
  );
}
