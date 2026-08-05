import { useMemo } from "react";
import type { CSSProperties } from "react";
import { Tag, Typography } from "antd";
import type { ReviewCategory, ReviewItem } from "../../entities/review";
import { useReviewWorkbenchStore } from "./store";

const { Text } = Typography;

interface ObjectThumbnailBarProps {
  items: ReviewItem[];
  categories: ReviewCategory[];
  onSelect: (id: string) => void;
}

export function ObjectThumbnailBar({
  items,
  categories,
  onSelect,
}: ObjectThumbnailBarProps) {
  const activeId = useReviewWorkbenchStore((s) => s.activeId);
  const statusFilter = useReviewWorkbenchStore((s) => s.statusFilter);
  const categoryFilter = useReviewWorkbenchStore((s) => s.categoryFilter);

  const categoryColorMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const c of categories) {
      map.set(c.id, c.color);
      map.set(c.display_name, c.color);
    }
    return map;
  }, [categories]);

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

  if (filteredItems.length === 0) return null;

  return (
    <div style={CONTAINER}>
      <div style={HEADER_TAG}>
        <Text style={{ fontSize: 11, color: "var(--text-secondary, #8c8c8c)" }}>
          对象列 ({filteredItems.length})
        </Text>
      </div>

      <div style={SCROLL_LIST}>
        {filteredItems.map((item, index) => {
          const isActive = activeId === item.id;
          const color = categoryColorMap.get(item.species) || "#52c99a";

          return (
            <div
              key={item.id}
              style={{
                ...THUMB_CARD,
                borderColor: isActive ? "#0e6e63" : "transparent",
                backgroundColor: isActive ? "rgba(14, 110, 99, 0.2)" : "rgba(125, 125, 125, 0.1)",
              }}
              onClick={() => onSelect(item.id)}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", backgroundColor: color }} />
                <Text style={{ fontSize: 11 }} ellipsis>
                  #{index + 1} {item.species || "未设置"}
                </Text>
              </div>
              {item.conflict && (
                <Tag color="red" style={{ margin: 0, fontSize: 9, padding: "0 2px", lineHeight: "14px" }}>
                  冲突
                </Tag>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

const CONTAINER: CSSProperties = {
  height: 48,
  display: "flex",
  alignItems: "center",
  borderTop: "1px solid var(--border-color, rgba(125, 125, 125, 0.15))",
  backgroundColor: "var(--bg-thumbbar, rgba(0, 0, 0, 0.1))",
  padding: "0 8px",
  overflow: "hidden",
};

const HEADER_TAG: CSSProperties = {
  paddingRight: 8,
  borderRight: "1px solid rgba(125, 125, 125, 0.2)",
  marginRight: 8,
  flexShrink: 0,
};

const SCROLL_LIST: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  overflowX: "auto",
  flex: 1,
  height: "100%",
  padding: "4px 0",
};

const THUMB_CARD: CSSProperties = {
  minWidth: 90,
  height: 34,
  padding: "0 8px",
  borderRadius: 4,
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  cursor: "pointer",
  border: "1.5px solid transparent",
  transition: "all 0.2s",
  flexShrink: 0,
};
