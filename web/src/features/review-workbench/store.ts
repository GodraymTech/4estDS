import { create } from "zustand";
import type { ReviewItem, ReviewPatch, ReviewWorkspace } from "../../entities/review";

export type WorkbenchTool = "select" | "draw" | "ai_text" | "ai_visual";
export type StatusFilterType = "all" | "accepted" | "pending" | "rejected" | "conflict";

export interface ReviewWorkbenchState {
  revision: number;
  itemsById: Record<string, ReviewItem>;
  order: string[];
  selectedIds: string[];
  activeId: string | null;
  
  // 画布与工具状态
  activeTool: WorkbenchTool;
  zoom: number;
  pan: { x: number; y: number };
  activeCategory: string | null;
  statusFilter: StatusFilterType;
  categoryFilter: string | null;
  isSyncing: boolean;
  maskEditingItemId: string | null;

  // 方法
  hydrate: (workspace: ReviewWorkspace) => void;
  replaceItems: (revision: number, items: ReviewItem[]) => void;
  applyPatch: (patch: ReviewPatch) => void;
  select: (id: string, additive?: boolean) => void;
  setSelectedIds: (ids: string[]) => void;
  clearSelection: () => void;
  setActiveTool: (tool: WorkbenchTool) => void;
  setZoom: (zoom: number | ((prev: number) => number)) => void;
  setPan: (pan: { x: number; y: number } | ((prev: { x: number; y: number }) => { x: number; y: number })) => void;
  setActiveCategory: (cat: string | null) => void;
  setStatusFilter: (filter: StatusFilterType) => void;
  setCategoryFilter: (cat: string | null) => void;
  setIsSyncing: (syncing: boolean) => void;
  setMaskEditingItemId: (id: string | null) => void;
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
  zoom: 1,
  pan: { x: 0, y: 0 },
  activeCategory: null,
  statusFilter: "all",
  categoryFilter: null,
  isSyncing: false,
  maskEditingItemId: null,

  hydrate: (workspace) => set({
    revision: workspace.revision,
    itemsById: indexItems(workspace.items),
    order: workspace.items.map((item) => item.id),
    selectedIds: [],
    activeId: workspace.items[0]?.id ?? null,
    activeCategory: workspace.active_category ?? workspace.category_catalog[0]?.id ?? null,
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
  setZoom: (zoom) => set((state) => ({ zoom: typeof zoom === "function" ? zoom(state.zoom) : zoom })),
  setPan: (pan) => set((state) => ({ pan: typeof pan === "function" ? pan(state.pan) : pan })),
  setActiveCategory: (cat) => set({ activeCategory: cat }),
  setStatusFilter: (filter) => set({ statusFilter: filter }),
  setCategoryFilter: (cat) => set({ categoryFilter: cat }),
  setIsSyncing: (isSyncing) => set({ isSyncing }),
  setMaskEditingItemId: (id) => set({ maskEditingItemId: id }),
}));
