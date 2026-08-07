import { useMemo, useState } from "react";
import { Alert, ColorPicker, Dropdown, Input, Tag, Tooltip, Typography } from "antd";
import { EyeInvisibleOutlined, EyeOutlined, MoreOutlined, PlusOutlined, SearchOutlined } from "@ant-design/icons";
import type { ReviewCategory, ReviewItem } from "../../entities/review";
import { useReviewWorkbenchStore } from "./store";

const { Text } = Typography;

export function CategoryPanel({ categories, items, freshMode = false, onAddCategory, onChangeColor, onCategoryAction }: {
  categories: ReviewCategory[];
  items: ReviewItem[];
  freshMode?: boolean;
  onAddCategory?: (name: string, color?: string) => void;
  onChangeColor?: (id: string, color: string) => void;
  onCategoryAction?: (id: string, action: "accept" | "reject" | "delete") => void;
}) {
  const [query, setQuery] = useState("");
  const activeCategory = useReviewWorkbenchStore((state) => state.activeCategory);
  const setActiveCategory = useReviewWorkbenchStore((state) => state.setActiveCategory);
  const hiddenCategories = useReviewWorkbenchStore((state) => state.hiddenCategories);
  const toggleCategoryVisibility = useReviewWorkbenchStore((state) => state.toggleCategoryVisibility);
  const counts = useMemo(() => {
    const result = new Map<string, number>();
    for (const item of items) result.set(item.species, (result.get(item.species) ?? 0) + 1);
    return result;
  }, [items]);
  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return normalized ? categories.filter((category) => `${category.display_name} ${category.id}`.toLowerCase().includes(normalized)) : categories;
  }, [categories, query]);
  const canCreate = Boolean(query.trim()) && !categories.some((category) => category.display_name === query.trim() || category.id === query.trim());
  const create = () => {
    if (!canCreate) return;
    onAddCategory?.(query.trim());
    setQuery("");
  };

  return (
    <div className="review-category-panel">
      {freshMode && categories.length === 0 ? <Alert type="info" showIcon message="请先创建至少一个树种类别，用于标注" /> : null}
      <div className="review-category-panel__search">
        <Input
          size="small"
          prefix={<SearchOutlined />}
          placeholder="搜索或输入新树种"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onPressEnter={create}
          suffix={canCreate ? (
            <Tooltip title={`创建“${query.trim()}”`}><Tag color="green" onClick={create} style={{ cursor: "pointer", margin: 0 }}><PlusOutlined /> 创建</Tag></Tooltip>
          ) : null}
        />
      </div>
      <div className="review-category-panel__list">
        {filtered.map((category, index) => {
          const active = activeCategory === category.id;
          const hidden = hiddenCategories.includes(category.id);
          return (
            <div key={category.id} className={`review-category-row${active ? " is-active" : ""}`} onClick={() => setActiveCategory(category.id)}>
              <ColorPicker size="small" value={category.color} disabledAlpha onChangeComplete={(color) => onChangeColor?.(category.id, color.toHexString())} />
              <div className="review-category-row__name">
                <Text strong={active} ellipsis>{category.display_name}</Text>
                {index < 9 ? <kbd>{index + 1}</kbd> : null}
              </div>
              <Tag bordered={false}>{counts.get(category.id) ?? counts.get(category.display_name) ?? 0}</Tag>
              <Tooltip title={hidden ? "显示该类别" : "隐藏该类别"}>
                <button className="review-icon-button" type="button" aria-label={hidden ? "显示类别" : "隐藏类别"} onClick={(event) => { event.stopPropagation(); toggleCategoryVisibility(category.id); }}>
                  {hidden ? <EyeInvisibleOutlined /> : <EyeOutlined />}
                </button>
              </Tooltip>
              <Dropdown
                trigger={["click"]}
                menu={{ items: [
                  { key: "accept", label: "批量接受" },
                  { key: "reject", label: "批量拒绝" },
                  { type: "divider" },
                  { key: "delete", label: "删除该类别可编辑框", danger: true },
                ], onClick: ({ key, domEvent }) => { domEvent.stopPropagation(); onCategoryAction?.(category.id, key as "accept" | "reject" | "delete"); } }}
              >
                <button className="review-icon-button" type="button" aria-label="类别批量操作" onClick={(event) => event.stopPropagation()}><MoreOutlined /></button>
              </Dropdown>
            </div>
          );
        })}
      </div>
    </div>
  );
}
