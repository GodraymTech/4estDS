import { useMemo } from "react";
import { Badge, Button, Checkbox, Collapse, Empty, Select, Space, Tag, Typography } from "antd";
import { CheckOutlined, CloseOutlined, DeleteOutlined, LockOutlined, WarningOutlined } from "@ant-design/icons";
import type { ReviewCategory, ReviewItem } from "../../entities/review";
import { useReviewWorkbenchStore, type StatusFilterType } from "./store";

const { Text } = Typography;

export function ObjectList({ items, categories, onSelect, onBulkStatus, onBulkDelete }: {
  items: ReviewItem[];
  categories: ReviewCategory[];
  onSelect: (id: string, additive?: boolean) => void;
  onBulkStatus?: (status: "accepted" | "rejected" | "pending") => void;
  onBulkDelete?: () => void;
}) {
  const selectedIds = useReviewWorkbenchStore((state) => state.selectedIds);
  const setSelectedIds = useReviewWorkbenchStore((state) => state.setSelectedIds);
  const activeId = useReviewWorkbenchStore((state) => state.activeId);
  const statusFilter = useReviewWorkbenchStore((state) => state.statusFilter);
  const setStatusFilter = useReviewWorkbenchStore((state) => state.setStatusFilter);
  const categoryFilter = useReviewWorkbenchStore((state) => state.categoryFilter);
  const setCategoryFilter = useReviewWorkbenchStore((state) => state.setCategoryFilter);
  const hiddenCategories = useReviewWorkbenchStore((state) => state.hiddenCategories);
  const categoryMap = useMemo(() => new Map(categories.flatMap((category) => [[category.id, category], [category.display_name, category]])), [categories]);
  const filtered = useMemo(() => items.filter((item) => {
    if (hiddenCategories.includes(item.species)) return false;
    if (categoryFilter && item.species !== categoryFilter) return false;
    if (statusFilter === "conflict") return Boolean(item.conflict);
    return statusFilter === "all" || item.status === statusFilter;
  }), [items, hiddenCategories, categoryFilter, statusFilter]);
  const groups = useMemo(() => {
    const result = new Map<string, ReviewItem[]>();
    for (const item of filtered) result.set(item.species || "未设置类别", [...(result.get(item.species || "未设置类别") ?? []), item]);
    return [...result.entries()];
  }, [filtered]);
  const allSelected = filtered.length > 0 && filtered.every((item) => selectedIds.includes(item.id));

  return (
    <div className="review-object-list">
      <div className="review-object-list__filters">
        <div className="review-object-list__select-all">
          <Checkbox checked={allSelected} indeterminate={!allSelected && filtered.some((item) => selectedIds.includes(item.id))} onChange={() => setSelectedIds(allSelected ? [] : filtered.map((item) => item.id))}>
            全选 ({filtered.length})
          </Checkbox>
          {selectedIds.length ? <Text type="secondary">已选 {selectedIds.length}</Text> : null}
        </div>
        <Space.Compact block>
          <Select size="small" value={statusFilter} onChange={(value) => setStatusFilter(value as StatusFilterType)} options={[
            { value: "all", label: "全部状态" }, { value: "accepted", label: "已接受" }, { value: "pending", label: "待确认" }, { value: "rejected", label: "已拒绝" }, { value: "conflict", label: "冲突" },
          ]} />
          <Select size="small" value={categoryFilter ?? ""} onChange={(value) => setCategoryFilter(value || null)} options={[{ value: "", label: "全部类别" }, ...categories.map((category) => ({ value: category.id, label: category.display_name }))]} />
        </Space.Compact>
      </div>
      {selectedIds.length ? (
        <div className="review-object-list__bulk">
          <Button size="small" type="primary" icon={<CheckOutlined />} onClick={() => onBulkStatus?.("accepted")}>接受</Button>
          <Button size="small" icon={<CloseOutlined />} onClick={() => onBulkStatus?.("rejected")}>拒绝</Button>
          <Button size="small" danger icon={<DeleteOutlined />} onClick={onBulkDelete}>删除可编辑项</Button>
        </div>
      ) : null}
      <div className="review-object-list__body">
        {!groups.length ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无匹配对象" /> : (
          <Collapse
            ghost
            size="small"
            defaultActiveKey={groups.map(([species]) => species)}
            items={groups.map(([species, group]) => ({
              key: species,
              label: <Space><span className="review-color-dot" style={{ background: categoryMap.get(species)?.color ?? "#72bc8f" }} /><Text strong>{categoryMap.get(species)?.display_name ?? species}</Text><Badge count={group.length} showZero color="#606b68" /></Space>,
              children: group.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className={`review-object-row${activeId === item.id ? " is-active" : ""}${selectedIds.includes(item.id) ? " is-selected" : ""}`}
                  onClick={(event) => onSelect(item.id, event.ctrlKey || event.metaKey)}
                >
                  <span className="review-object-row__id">#{item.id.slice(-6)}</span>
                  {item.frozen ? <LockOutlined title="冻结框" /> : null}
                  {item.conflict ? <WarningOutlined className="review-object-row__warning" title="与正式结果冲突" /> : null}
                  {item.confidence != null ? <Text type="secondary">{Math.round(item.confidence * 100)}%</Text> : null}
                  <Tag color={item.status === "accepted" ? "success" : item.status === "rejected" ? "error" : "warning"}>{item.status === "accepted" ? "接受" : item.status === "rejected" ? "拒绝" : "待定"}</Tag>
                </button>
              )),
            }))}
          />
        )}
      </div>
    </div>
  );
}
