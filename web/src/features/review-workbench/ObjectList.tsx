import { useMemo } from "react";
import type { CSSProperties } from "react";
import { Button, Checkbox, Select, Space, Tag, Typography, Empty } from "antd";
import { CheckOutlined, CloseOutlined, DeleteOutlined, WarningOutlined } from "@ant-design/icons";
import type { ReviewCategory, ReviewItem } from "../../entities/review";
import { useReviewWorkbenchStore, type StatusFilterType } from "./store";

const { Text } = Typography;

interface ObjectListProps {
  items: ReviewItem[];
  categories: ReviewCategory[];
  onSelect: (id: string, additive?: boolean) => void;
  onBulkStatus?: (status: "accepted" | "rejected" | "pending") => void;
  onBulkDelete?: () => void;
}

export function ObjectList({
  items,
  categories,
  onSelect,
  onBulkStatus,
  onBulkDelete,
}: ObjectListProps) {
  const selectedIds = useReviewWorkbenchStore((s) => s.selectedIds);
  const setSelectedIds = useReviewWorkbenchStore((s) => s.setSelectedIds);
  const activeId = useReviewWorkbenchStore((s) => s.activeId);
  const statusFilter = useReviewWorkbenchStore((s) => s.statusFilter);
  const setStatusFilter = useReviewWorkbenchStore((s) => s.setStatusFilter);
  const categoryFilter = useReviewWorkbenchStore((s) => s.categoryFilter);
  const setCategoryFilter = useReviewWorkbenchStore((s) => s.setCategoryFilter);

  const categoryColorMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const c of categories) {
      map.set(c.id, c.color);
      map.set(c.display_name, c.color);
    }
    return map;
  }, [categories]);

  // 根据过滤条件处理
  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      if (categoryFilter && item.species !== categoryFilter) return false;
      if (statusFilter === "accepted" && item.status !== "accepted") return false;
      if (statusFilter === "rejected" && item.status !== "rejected") return false;
      if (statusFilter === "pending" && item.status !== "pending") return false;
      if (statusFilter === "conflict" && !item.conflict) return false;
      return true;
    });
  }, [items, categoryFilter, statusFilter]);

  const allFilteredSelected = filteredItems.length > 0 && filteredItems.every((i) => selectedIds.includes(i.id));

  const toggleSelectAll = () => {
    if (allFilteredSelected) {
      setSelectedIds([]);
    } else {
      setSelectedIds(filteredItems.map((i) => i.id));
    }
  };

  return (
    <div style={CONTAINER}>
      {/* 头部过滤器 */}
      <div style={HEADER}>
        <Space direction="vertical" size={8} style={{ width: "100%" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <Checkbox checked={allFilteredSelected} onChange={toggleSelectAll}>
              <Text strong>全选 ({filteredItems.length})</Text>
            </Checkbox>
            {selectedIds.length > 0 && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                已选 {selectedIds.length} 项
              </Text>
            )}
          </div>

          <div style={{ display: "flex", gap: 6 }}>
            <Select
              size="small"
              style={{ flex: 1 }}
              value={statusFilter}
              options={[
                { value: "all", label: "全部状态" },
                { value: "accepted", label: "已接受" },
                { value: "pending", label: "待确认" },
                { value: "rejected", label: "已拒绝" },
                { value: "conflict", label: "冲突" },
              ]}
              onChange={(v) => setStatusFilter(v as StatusFilterType)}
            />
            <Select
              size="small"
              style={{ flex: 1 }}
              value={categoryFilter ?? ""}
              options={[
                { value: "", label: "全部类别" },
                ...categories.map((c) => ({ value: c.id, label: c.display_name })),
              ]}
              onChange={(v) => setCategoryFilter(v || null)}
            />
          </div>
        </Space>
      </div>

      {/* 批量操作条 */}
      {selectedIds.length > 0 && (
        <div style={BULK_BAR}>
          <Space size={4}>
            <Button
              size="small"
              type="primary"
              icon={<CheckOutlined />}
              onClick={() => onBulkStatus?.("accepted")}
            >
              接受
            </Button>
            <Button
              size="small"
              icon={<CloseOutlined />}
              onClick={() => onBulkStatus?.("rejected")}
            >
              拒绝
            </Button>
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              onClick={onBulkDelete}
            >
              删除
            </Button>
          </Space>
        </div>
      )}

      {/* 列表主体 */}
      <div style={LIST_BODY}>
        {filteredItems.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无匹配的对象" />
        ) : (
          filteredItems.map((item) => {
            const isSelected = selectedIds.includes(item.id);
            const isActive = activeId === item.id;
            const color = categoryColorMap.get(item.species) || "#52c99a";

            return (
              <div
                key={item.id}
                style={{
                  ...ITEM_ROW,
                  backgroundColor: isActive
                    ? "rgba(14, 110, 99, 0.18)"
                    : isSelected
                    ? "rgba(14, 110, 99, 0.08)"
                    : undefined,
                  borderLeft: item.conflict
                    ? "3px solid #ff4d4f"
                    : isSelected
                    ? "3px solid #0e6e63"
                    : "3px solid transparent",
                }}
                onClick={(e) => onSelect(item.id, e.ctrlKey || e.metaKey)}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8, flex: 1, minWidth: 0 }}>
                  <span style={{ width: 10, height: 10, borderRadius: "50%", backgroundColor: color, flexShrink: 0 }} />
                  <Text ellipsis style={{ flex: 1, fontSize: 13 }}>
                    {item.species || "未标注树种"}
                  </Text>
                  {item.conflict && (
                    <WarningOutlined style={{ color: "#ff4d4f", fontSize: 13 }} title="与已有正式结果冲突" />
                  )}
                  {item.confidence !== undefined && item.confidence !== null && (
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      {(item.confidence * 100).toFixed(0)}%
                    </Text>
                  )}
                  <Tag
                    color={
                      item.status === "accepted"
                        ? "success"
                        : item.status === "rejected"
                        ? "error"
                        : "warning"
                    }
                    style={{ margin: 0, fontSize: 11 }}
                  >
                    {item.status === "accepted" ? "接受" : item.status === "rejected" ? "拒绝" : "待定"}
                  </Tag>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

const CONTAINER: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  height: "100%",
};

const HEADER: CSSProperties = {
  padding: 10,
  borderBottom: "1px solid var(--border-color, rgba(125, 125, 125, 0.15))",
};

const BULK_BAR: CSSProperties = {
  padding: "6px 10px",
  backgroundColor: "rgba(14, 110, 99, 0.08)",
  borderBottom: "1px solid var(--border-color, rgba(125, 125, 125, 0.15))",
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
};

const LIST_BODY: CSSProperties = {
  flex: 1,
  overflowY: "auto",
  padding: "4px 0",
};

const ITEM_ROW: CSSProperties = {
  padding: "6px 10px",
  display: "flex",
  alignItems: "center",
  cursor: "pointer",
  transition: "background 0.2s",
  borderBottom: "1px solid rgba(125, 125, 125, 0.05)",
};
