import { useState, useMemo } from "react";
import type { CSSProperties } from "react";
import { Input, Tag, Space, Typography, Tooltip, ColorPicker } from "antd";
import { PlusOutlined, SearchOutlined } from "@ant-design/icons";
import type { ReviewCategory, ReviewItem } from "../../entities/review";
import { useReviewWorkbenchStore } from "./store";

const { Text } = Typography;

interface CategoryPanelProps {
  categories: ReviewCategory[];
  items: ReviewItem[];
  onAddCategory?: (name: string, color?: string) => void;
  onChangeColor?: (id: string, color: string) => void;
}

export function CategoryPanel({
  categories,
  items,
  onAddCategory,
  onChangeColor,
}: CategoryPanelProps) {
  const [query, setQuery] = useState("");
  const activeCategory = useReviewWorkbenchStore((s) => s.activeCategory);
  const setActiveCategory = useReviewWorkbenchStore((s) => s.setActiveCategory);

  // 统计每个类别的数量
  const counts = useMemo(() => {
    const map = new Map<string, number>();
    for (const item of items) {
      if (item.species) {
        map.set(item.species, (map.get(item.species) || 0) + 1);
      }
    }
    return map;
  }, [items]);

  const filtered = useMemo(() => {
    if (!query.trim()) return categories;
    return categories.filter(
      (c) =>
        c.display_name.toLowerCase().includes(query.toLowerCase()) ||
        c.id.toLowerCase().includes(query.toLowerCase())
    );
  }, [categories, query]);

  const canCreate = query.trim().length > 0 && !categories.some((c) => c.display_name === query.trim());

  const handleCreate = () => {
    if (canCreate) {
      onAddCategory?.(query.trim());
      setQuery("");
    }
  };

  return (
    <div style={CONTAINER}>
      {/* 搜索与新增输入框 */}
      <div style={{ padding: "8px 10px" }}>
        <Input
          size="small"
          prefix={<SearchOutlined style={{ color: "#8c8c8c" }} />}
          placeholder="搜索或输入创建新树种类别..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onPressEnter={handleCreate}
          suffix={
            canCreate ? (
              <Tooltip title={`按 Enter 创建 "${query}"`}>
                <Tag color="green" style={{ cursor: "pointer", margin: 0 }} onClick={handleCreate}>
                  <PlusOutlined /> 创建
                </Tag>
              </Tooltip>
            ) : null
          }
        />
      </div>

      {/* 类别标签云/列表 */}
      <div style={CAT_LIST}>
        {filtered.map((cat) => {
          const isSelected = activeCategory === cat.id || activeCategory === cat.display_name;
          const count = counts.get(cat.id) || counts.get(cat.display_name) || 0;

          return (
            <div
              key={cat.id}
              style={{
                ...CAT_ITEM,
                backgroundColor: isSelected ? "rgba(14, 110, 99, 0.18)" : undefined,
                borderColor: isSelected ? "#0e6e63" : "transparent",
              }}
              onClick={() => setActiveCategory(cat.id)}
            >
              <Space size={6}>
                <ColorPicker
                  value={cat.color}
                  size="small"
                  onChangeComplete={(color) => onChangeColor?.(cat.id, color.toHexString())}
                />
                <Text strong={isSelected} style={{ fontSize: 13 }}>
                  {cat.display_name}
                </Text>
              </Space>
              <Tag style={{ margin: 0, borderRadius: 10, fontSize: 11 }}>{count}</Tag>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const CONTAINER: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  borderBottom: "1px solid var(--border-color, rgba(125, 125, 125, 0.15))",
};

const CAT_LIST: CSSProperties = {
  padding: "4px 8px 8px 8px",
  maxHeight: 140,
  overflowY: "auto",
  display: "flex",
  flexDirection: "column",
  gap: 4,
};

const CAT_ITEM: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  padding: "4px 8px",
  borderRadius: 4,
  cursor: "pointer",
  border: "1px solid transparent",
  transition: "all 0.2s",
};
