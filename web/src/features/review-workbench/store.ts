import { create } from "zustand";
import type { ReviewItem, ReviewWorkspace } from "../../entities/review";

interface ReviewWorkbenchState {
  revision: number;
  itemsById: Record<string, ReviewItem>;
  order: string[];
  selectedIds: string[];
  activeId: string | null;
  hydrate: (workspace: ReviewWorkspace) => void;
  replaceItems: (revision: number, items: ReviewItem[]) => void;
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
  select: (id, additive = false) => set((state) => ({
    activeId: id,
    selectedIds: additive
      ? state.selectedIds.includes(id) ? state.selectedIds.filter((value) => value !== id) : [...state.selectedIds, id]
      : [id],
  })),
  clearSelection: () => set({ selectedIds: [], activeId: null }),
}));
