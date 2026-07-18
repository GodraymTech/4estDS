import { create } from "zustand";
import type { ReviewItem, ReviewPatch, ReviewWorkspace } from "../../entities/review";

interface ReviewWorkbenchState {
  revision: number;
  itemsById: Record<string, ReviewItem>;
  order: string[];
  selectedIds: string[];
  activeId: string | null;
  hydrate: (workspace: ReviewWorkspace) => void;
  replaceItems: (revision: number, items: ReviewItem[]) => void;
  applyPatch: (patch: ReviewPatch) => void;
  select: (id: string, additive?: boolean) => void;
  clearSelection: () => void;
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
  hydrate: (workspace) => set({
    revision: workspace.revision,
    itemsById: indexItems(workspace.items),
    order: workspace.items.map((item) => item.id),
    selectedIds: [],
    activeId: workspace.items[0]?.id ?? null,
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
  clearSelection: () => set({ selectedIds: [], activeId: null }),
}));
