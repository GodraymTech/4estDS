import { useMemo } from "react";
import { Badge, Collapse, Empty, Space, Tag, Tooltip, Typography } from "antd";
import { DeleteOutlined, EyeInvisibleOutlined, EyeOutlined, LockOutlined, WarningOutlined } from "@ant-design/icons";
import type { ReviewCategory, ReviewItem } from "../../entities/review";
import { useReviewWorkbenchStore } from "./store";

const { Text } = Typography;

export function ObjectList({
  items,
  categories,
  onSelect,
  onDeleteSingle,
}: {
  items: ReviewItem[];
  categories: ReviewCategory[];
  onSelect: (id: string, additive?: boolean) => void;
  onDeleteSingle?: (id: string) => void;
}) {
  const selectedIds = useReviewWorkbenchStore((state) => state.selectedIds);
  const activeId = useReviewWorkbenchStore((state) => state.activeId);
  const categoryFilter = useReviewWorkbenchStore((state) => state.categoryFilter);
  const hiddenCategories = useReviewWorkbenchStore((state) => state.hiddenCategories);
  const hiddenItemIds = useReviewWorkbenchStore((state) => state.hiddenItemIds);
  const toggleItemVisibility = useReviewWorkbenchStore((state) => state.toggleItemVisibility);

  const categoryMap = useMemo(
    () => new Map(categories.flatMap((category) => [[category.id, category], [category.display_name, category]])),
    [categories],
  );

  const filtered = useMemo(() => {
    return items.filter((item) => {
      if (hiddenCategories.includes(item.species)) return false;
      if (categoryFilter && item.species !== categoryFilter) return false;
      return true;
    });
  }, [items, hiddenCategories, categoryFilter]);

  const groups = useMemo(() => {
    const result = new Map<string, ReviewItem[]>();
    for (const item of filtered) {
      const key = item.species || "未设置类别";
      result.set(key, [...(result.get(key) ?? []), item]);
    }
    return [...result.entries()];
  }, [filtered]);

  return (
    <div className="review-object-list">
      {/* 优雅的标题行 */}
      <div className="review-object-header">
        <span className="review-object-header__title">检测对象列表</span>
        <Tag bordered={false} style={{ margin: 0 }}>共 {filtered.length} 个</Tag>
      </div>

      {/* 对象列表项 */}
      <div className="review-object-list__body">
        {!groups.length ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无匹配对象" />
        ) : (
          <Collapse
            ghost
            size="small"
            defaultActiveKey={groups.map(([species]) => species)}
            items={groups.map(([species, group]) => ({
              key: species,
              label: (
                <Space>
                  <span className="review-color-dot" style={{ background: categoryMap.get(species)?.color ?? "#72bc8f" }} />
                  <Text strong>{categoryMap.get(species)?.display_name ?? species}</Text>
                  <Badge count={group.length} showZero color="#606b68" />
                </Space>
              ),
              children: group.map((item, idx) => {
                const isSelected = selectedIds.includes(item.id);
                const isActive = activeId === item.id;
                const isHidden = hiddenItemIds.includes(item.id);
                const confDisplay = item.confidence != null ? Number(item.confidence).toFixed(2) : "1.00";

                return (
                  <div
                    key={item.id}
                    className={`review-object-row${isActive ? " is-active" : ""}${isSelected ? " is-selected" : ""}${isHidden ? " is-hidden" : ""}`}
                    onClick={(event) => onSelect(item.id, event.ctrlKey || event.metaKey)}
                  >
                    <span className="review-object-row__id"># {String(idx + 1).padStart(2, "0")}</span>
                    {item.frozen ? <LockOutlined title="冻结框（存量真值已锁定）" /> : null}
                    {item.conflict ? <WarningOutlined className="review-object-row__warning" title="与存量正式结果冲突" /> : null}
                    <Tooltip title={`置信度`}>
                      <Text type="secondary" style={{ fontSize: 11, fontVariantNumeric: "tabular-nums", fontFamily: "monospace" }}>
                        {confDisplay}
                      </Text>
                    </Tooltip>

                    <div className="review-object-row__actions" onClick={(e) => e.stopPropagation()}>
                      <Tooltip title={isHidden ? "显示该对象" : "隐藏该对象"}>
                        <button
                          className="review-icon-button"
                          type="button"
                          aria-label={isHidden ? "显示该对象" : "隐藏该对象"}
                          onClick={() => toggleItemVisibility(item.id)}
                        >
                          {isHidden ? <EyeInvisibleOutlined /> : <EyeOutlined />}
                        </button>
                      </Tooltip>
                      <Tooltip title={item.frozen ? "冻结框不可删除" : "删除该对象"}>
                        <button
                          className="review-icon-button review-icon-button--danger"
                          type="button"
                          disabled={Boolean(item.frozen)}
                          aria-label="删除该对象"
                          onClick={() => onDeleteSingle?.(item.id)}
                        >
                          <DeleteOutlined />
                        </button>
                      </Tooltip>
                    </div>
                  </div>
                );
              }),
            }))}
          />
        )}
      </div>
    </div>
  );
}
