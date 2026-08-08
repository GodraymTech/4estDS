import { create } from "zustand";
import type { ReviewItem, ReviewPatch, ReviewWorkspace } from "../../entities/review";
import type { ReviewMergeMode } from "../../shared/api/types";

/** 选择与平移、手动画框、AI 交互工具 */
export type WorkbenchTool = "select" | "draw" | "ai_text" | "ai_visual";

/** AI 识别范围滑杆左端对应的最小边长(全局像素)。 */
export const MIN_REGION_SIDE_PX = 1280;
export type StatusFilterType = "all" | "accepted" | "pending" | "rejected" | "conflict";

export interface ReviewWorkbenchState {
  revision: number;
  itemsById: Record<string, ReviewItem>;
  order: string[];
  selectedIds: string[];
  activeId: string | null;
  
  // 画布与工具状态
  activeTool: WorkbenchTool;
  /** 选择与平移的交替开关: false 为默认[左键选择/框选, 右键平移]; true 为反转[左键平移, 右键选择/框选] */
  selectPanInverted: boolean;
  zoom: number;
  pan: { x: number; y: number };
  activeCategory: string | null;
  statusFilter: StatusFilterType;
  categoryFilter: string | null;
  isSyncing: boolean;
  maskEditingItemId: string | null;

  // 类别与单个对象可见性
  hiddenCategories: string[];
  hiddenItemIds: string[];

  // AI 识别范围与写入策略(画布矩形图层与 AI 面板共享一份真相)
  regionSidePx: number;
  regionMetricsVisible: boolean;
  mergeMode: ReviewMergeMode;
  autoTrigger: boolean;

  // 方法
  hydrate: (workspace: ReviewWorkspace) => void;
  replaceItems: (revision: number, items: ReviewItem[]) => void;
  applyPatch: (patch: ReviewPatch) => void;
  select: (id: string, additive?: boolean) => void;
  setSelectedIds: (ids: string[]) => void;
  clearSelection: () => void;
  setActiveTool: (tool: WorkbenchTool) => void;
  toggleSelectPanInversion: () => void;
  setSelectPanInverted: (inverted: boolean) => void;
  setZoom: (zoom: number | ((prev: number) => number)) => void;
  setPan: (pan: { x: number; y: number } | ((prev: { x: number; y: number }) => { x: number; y: number })) => void;
  setActiveCategory: (cat: string | null) => void;
  setStatusFilter: (filter: StatusFilterType) => void;
  setCategoryFilter: (cat: string | null) => void;
  setIsSyncing: (syncing: boolean) => void;
  setMaskEditingItemId: (id: string | null) => void;
  toggleCategoryVisibility: (categoryId: string) => void;
  setHiddenCategories: (ids: string[]) => void;
  toggleItemVisibility: (itemId: string) => void;
  setHiddenItemIds: (ids: string[]) => void;
  setRegionSidePx: (side: number) => void;
  setRegionMetricsVisible: (visible: boolean) => void;
  setMergeMode: (mode: ReviewMergeMode) => void;
  setAutoTrigger: (enabled: boolean) => void;
}

function indexItems(items: ReviewItem[]) {
  return Object.fromEntries(items.map((item) => [item.id, item]));
}

export const useReviewWorkbenchStore = create<ReviewWorkbenchState>((set) => ({
  revision: 0,
  itemsById: {},
  order: [],
  selectedIds: [],
  activeId: null,

  activeTool: "select",
  selectPanInverted: false,
  zoom: 1,
  pan: { x: 0, y: 0 },
  activeCategory: null,
  statusFilter: "all",
  categoryFilter: null,
  isSyncing: false,
  maskEditingItemId: null,

  hiddenCategories: [],
  hiddenItemIds: [],
  regionSidePx: MIN_REGION_SIDE_PX,
  regionMetricsVisible: false,
  mergeMode: "append",
  autoTrigger: true,

  hydrate: (workspace) => set({
    revision: workspace.revision,
    itemsById: indexItems(workspace.items),
    order: workspace.items.map((item) => item.id),
    selectedIds: [],
    activeId: workspace.items[0]?.id ?? null,
    activeCategory: workspace.active_category ?? workspace.category_catalog[0]?.id ?? null,
    hiddenItemIds: [],
    // 后端给出显式可见列表时取其补集作为隐藏项, 未给出则视为全部可见。
    hiddenCategories: workspace.visible_categories?.length
      ? workspace.category_catalog
          .filter((category) => !workspace.visible_categories.includes(category.id))
          .map((category) => category.id)
      : [],
  }),
  replaceItems: (revision, items) => set((state) => ({
    revision,
    itemsById: indexItems(items),
    order: items.map((item) => item.id),
    selectedIds: state.selectedIds.filter((id) => items.some((item) => item.id === id)),
    activeId: state.activeId && items.some((item) => item.id === state.activeId) ? state.activeId : items[0]?.id ?? null,
  })),
  applyPatch: (patch) => set((state) => {
    if (patch.replace_all) {
      const ids = new Set(patch.items.map((item) => item.id));
      return {
        revision: patch.revision,
        itemsById: indexItems(patch.items),
        order: patch.items.map((item) => item.id),
        selectedIds: state.selectedIds.filter((id) => ids.has(id)),
        activeId: state.activeId && ids.has(state.activeId) ? state.activeId : patch.items[0]?.id ?? null,
      };
    }
    const itemsById = { ...state.itemsById };
    const deleted = new Set(patch.deleted_item_ids);
    for (const id of deleted) delete itemsById[id];
    for (const item of patch.changed_items) itemsById[item.id] = item;
    const known = new Set(state.order);
    const order = state.order.filter((id) => !deleted.has(id));
    for (const item of patch.changed_items) {
      if (!known.has(item.id)) order.push(item.id);
    }
    return {
      revision: patch.revision,
      itemsById,
      order,
      selectedIds: state.selectedIds.filter((id) => !deleted.has(id)),
      activeId: state.activeId && !deleted.has(state.activeId) ? state.activeId : order[0] ?? null,
    };
  }),
  select: (id, additive = false) => set((state) => ({
    activeId: id,
    selectedIds: additive
      ? state.selectedIds.includes(id) ? state.selectedIds.filter((value) => value !== id) : [...state.selectedIds, id]
      : [id],
  })),
  setSelectedIds: (ids) => set({ selectedIds: ids, activeId: ids[0] ?? null }),
  clearSelection: () => set({ selectedIds: [], activeId: null }),
  setActiveTool: (tool) => set({ activeTool: tool }),
  toggleSelectPanInversion: () => set((state) => ({ selectPanInverted: !state.selectPanInverted })),
  setSelectPanInverted: (selectPanInverted) => set({ selectPanInverted }),
  setZoom: (zoom) => set((state) => ({ zoom: typeof zoom === "function" ? zoom(state.zoom) : zoom })),
  setPan: (pan) => set((state) => ({ pan: typeof pan === "function" ? pan(state.pan) : pan })),
  setActiveCategory: (cat) => set({ activeCategory: cat }),
  setStatusFilter: (filter) => set({ statusFilter: filter }),
  setCategoryFilter: (cat) => set({ categoryFilter: cat }),
  setIsSyncing: (isSyncing) => set({ isSyncing }),
  setMaskEditingItemId: (id) => set({ maskEditingItemId: id }),
  toggleCategoryVisibility: (categoryId) => set((state) => ({
    hiddenCategories: state.hiddenCategories.includes(categoryId)
      ? state.hiddenCategories.filter((value) => value !== categoryId)
      : [...state.hiddenCategories, categoryId],
  })),
  setHiddenCategories: (ids) => set({ hiddenCategories: ids }),
  toggleItemVisibility: (itemId) => set((state) => ({
    hiddenItemIds: state.hiddenItemIds.includes(itemId)
      ? state.hiddenItemIds.filter((value) => value !== itemId)
      : [...state.hiddenItemIds, itemId],
  })),
  setHiddenItemIds: (ids) => set({ hiddenItemIds: ids }),
  setRegionSidePx: (side) => set({ regionSidePx: Math.max(1, Math.round(side)) }),
  setRegionMetricsVisible: (regionMetricsVisible) => set({ regionMetricsVisible }),
  setMergeMode: (mergeMode) => set({ mergeMode }),
  setAutoTrigger: (autoTrigger) => set({ autoTrigger }),
}));
