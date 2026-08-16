import { beforeEach, describe, expect, it } from "vitest";
import type { ReviewItem } from "../../entities/review";
import { useReviewWorkbenchStore } from "./store";

function item(index: number): ReviewItem {
  return {
    id: `item-${index}`,
    species: "红树",
    box_px: [index, index, index + 1, index + 1],
    source: "human",
    confirmed: true,
    status: "accepted",
  };
}

describe("review workbench incremental patch", () => {
  beforeEach(() => useReviewWorkbenchStore.setState({
    revision: 0,
    itemsById: {},
    order: [],
    selectedIds: [],
    activeId: null,
  }));

  it("keeps unchanged object identities in a 10k workspace", () => {
    const items = Array.from({ length: 10_000 }, (_, index) => item(index));
    useReviewWorkbenchStore.getState().hydrate({
      revision: 0,
      items,
      category_catalog: [],
      visible_categories: [],
      text_prompts: [],
      visual_exemplars: [],
      attempts: [],
    });
    const untouched = useReviewWorkbenchStore.getState().itemsById["item-9999"];
    const changed = { ...items[5], species: "秋茄" };

    useReviewWorkbenchStore.getState().applyPatch({
      session_id: "session",
      revision: 1,
      items: [],
      summary: {},
      changed_items: [changed],
      deleted_item_ids: [],
      replace_all: false,
    });

    const state = useReviewWorkbenchStore.getState();
    expect(state.itemsById["item-5"].species).toBe("秋茄");
    expect(state.itemsById["item-9999"]).toBe(untouched);
    expect(state.order).toHaveLength(10_000);
  });

  it("preserves user-selected activeCategory across workspace hydration", () => {
    useReviewWorkbenchStore.getState().hydrate({
      revision: 0,
      items: [],
      category_catalog: [
        { id: "cat-1", display_name: "树种1", model_prompt: "树种1", color: "#3b82f6" },
        { id: "cat-2", display_name: "树种2", model_prompt: "树种2", color: "#f97316" },
      ],
      visible_categories: [],
      text_prompts: [],
      visual_exemplars: [],
      attempts: [],
    });
    // 初始默认为首个树种
    expect(useReviewWorkbenchStore.getState().activeCategory).toBe("cat-1");

    // 用户手动设定为树种2
    useReviewWorkbenchStore.getState().setActiveCategory("cat-2");
    expect(useReviewWorkbenchStore.getState().activeCategory).toBe("cat-2");

    // 画框或收到新 revision 再次触发 hydrate，不应被重置为首个树种
    useReviewWorkbenchStore.getState().hydrate({
      revision: 1,
      items: [item(0)],
      category_catalog: [
        { id: "cat-1", display_name: "树种1", model_prompt: "树种1", color: "#3b82f6" },
        { id: "cat-2", display_name: "树种2", model_prompt: "树种2", color: "#f97316" },
      ],
      visible_categories: [],
      text_prompts: [],
      visual_exemplars: [],
      attempts: [],
    });
    expect(useReviewWorkbenchStore.getState().activeCategory).toBe("cat-2");
  });
});
