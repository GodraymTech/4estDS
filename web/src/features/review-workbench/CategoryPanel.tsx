import { useEffect, useMemo, useRef, useState } from "react";
import { App, Button, ColorPicker, Input, type InputRef, Tag, Tooltip, Typography } from "antd";
import { DeleteOutlined, EditOutlined, EyeInvisibleOutlined, EyeOutlined, PlusOutlined } from "@ant-design/icons";
import type { ReviewCategory, ReviewItem } from "../../entities/review";
import { useReviewWorkbenchStore } from "./store";

const { Text } = Typography;

export function CategoryPanel({
  categories,
  items,
  freshMode = false,
  onAddCategory,
  onRenameCategory,
  onChangeColor,
  onCategoryAction,
}: {
  categories: ReviewCategory[];
  items: ReviewItem[];
  freshMode?: boolean;
  onAddCategory?: (name: string, color?: string) => void;
  onRenameCategory?: (id: string, newDisplayName: string) => void;
  onChangeColor?: (id: string, color: string) => void;
  onCategoryAction?: (id: string, action: "delete") => void;
}) {
  const { modal } = App.useApp();
  const [isAdding, setIsAdding] = useState(false);
  const [newSpeciesName, setNewSpeciesName] = useState("");
  const addInputRef = useRef<InputRef>(null);
  const hasPromptedEmptyRef = useRef(false);

  const activeCategory = useReviewWorkbenchStore((state) => state.activeCategory);
  const setActiveCategory = useReviewWorkbenchStore((state) => state.setActiveCategory);
  const hiddenCategories = useReviewWorkbenchStore((state) => state.hiddenCategories);
  const toggleCategoryVisibility = useReviewWorkbenchStore((state) => state.toggleCategoryVisibility);

  // 空列表时全局弹窗引导，确认后直接跳到输入打字位置
  useEffect(() => {
    if (freshMode && categories.length === 0 && !hasPromptedEmptyRef.current) {
      hasPromptedEmptyRef.current = true;
      modal.info({
        title: "请先添加树种",
        content: "当前会话尚未配置树种类别。请至少添加一个新树种名称。",
        okText: "立即添加树种",
        onOk: () => {
          setIsAdding(true);
          setTimeout(() => addInputRef.current?.focus(), 120);
        },
      });
    }
  }, [freshMode, categories.length, modal]);

  const counts = useMemo(() => {
    const result = new Map<string, number>();
    for (const item of items) result.set(item.species, (result.get(item.species) ?? 0) + 1);
    return result;
  }, [items]);

  const handleConfirmAdd = () => {
    const trimmed = newSpeciesName.trim();
    if (trimmed) {
      onAddCategory?.(trimmed);
      setNewSpeciesName("");
      setIsAdding(false);
    }
  };

  const promptRename = (cat: ReviewCategory) => {
    let currentVal = cat.display_name;
    modal.confirm({
      title: `重命名类别：${cat.display_name}`,
      content: (
        <div style={{ marginTop: 12 }}>
          <Input
            defaultValue={cat.display_name}
            placeholder="请输入新的类别名称"
            autoFocus
            onChange={(e) => { currentVal = e.target.value; }}
            onPressEnter={() => {
              const trimmed = currentVal.trim();
              if (trimmed && trimmed !== cat.display_name) {
                onRenameCategory?.(cat.id, trimmed);
              }
            }}
          />
        </div>
      ),
      okText: "确认修改",
      cancelText: "取消",
      onOk: () => {
        const trimmed = currentVal.trim();
        if (trimmed && trimmed !== cat.display_name) {
          onRenameCategory?.(cat.id, trimmed);
        }
      },
    });
  };

  return (
    <div className="review-category-panel">
      {/* 优雅的标题行：左侧树种列表标题，右端新增树种图标与丝滑向左展开的输入框 */}
      <div className="review-category-header">
        <span className="review-category-header__title">树种列表</span>
        <div className="review-category-header__actions">
          <div className={`review-category-input-wrapper${isAdding ? " is-expanded" : ""}`}>
            <Input
              ref={addInputRef}
              size="small"
              placeholder="全英文;无空格"
              value={newSpeciesName}
              onChange={(e) => setNewSpeciesName(e.target.value)}
              onPressEnter={handleConfirmAdd}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  setIsAdding(false);
                  setNewSpeciesName("");
                }
              }}
              onBlur={() => {
                if (!newSpeciesName.trim()) {
                  setIsAdding(false);
                }
              }}
            />
          </div>
          <Tooltip title="新增树种">
            <Button
              type="text"
              size="small"
              className="review-icon-button"
              icon={<PlusOutlined />}
              aria-label="新增树种"
              onClick={() => {
                setIsAdding(true);
                setTimeout(() => addInputRef.current?.focus(), 60);
              }}
            />
          </Tooltip>
        </div>
      </div>

      <div className="review-category-panel__list">
        {categories.map((category, index) => {
          const active = activeCategory === category.id;
          const hidden = hiddenCategories.includes(category.id);

          return (
            <div
              key={category.id}
              className={`review-category-row${active ? " is-active" : ""}`}
              onClick={() => setActiveCategory(category.id)}
            >
              <ColorPicker
                size="small"
                value={category.color}
                disabledAlpha
                onChangeComplete={(color) => onChangeColor?.(category.id, color.toHexString())}
              />
              <div className="review-category-row__name">
                <Text strong={active} ellipsis>{category.display_name}</Text>
                {index < 9 ? (
                  <Tooltip title={`快捷键 ${index + 1}`}>
                    <kbd>{index + 1}</kbd>
                  </Tooltip>
                ) : null}
              </div>
              <Tag bordered={false}>{counts.get(category.id) ?? counts.get(category.display_name) ?? 0}</Tag>
              <Tooltip title={hidden ? "显示" : "隐藏"}>
                <button
                  className="review-icon-button"
                  type="button"
                  aria-label={hidden ? "显示类别" : "隐藏类别"}
                  onClick={(event) => {
                    event.stopPropagation();
                    toggleCategoryVisibility(category.id);
                  }}
                >
                  {hidden ? <EyeInvisibleOutlined /> : <EyeOutlined />}
                </button>
              </Tooltip>
              <Tooltip title="重命名">
                <button
                  className="review-icon-button"
                  type="button"
                  aria-label="重命名类别"
                  onClick={(event) => {
                    event.stopPropagation();
                    promptRename(category);
                  }}
                >
                  <EditOutlined />
                </button>
              </Tooltip>
              <Tooltip title="删除该类">
                <button
                  className="review-icon-button review-icon-button--danger"
                  type="button"
                  aria-label="删除类别可编辑框"
                  onClick={(event) => {
                    event.stopPropagation();
                    onCategoryAction?.(category.id, "delete");
                  }}
                >
                  <DeleteOutlined />
                </button>
              </Tooltip>
            </div>
          );
        })}
      </div>
    </div>
  );
}
