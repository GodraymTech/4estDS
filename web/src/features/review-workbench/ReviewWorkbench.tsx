import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Empty, Modal, Select, Spin, Tabs, Typography, message } from "antd";
import { CheckOutlined, CloseOutlined, DeleteOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { operationId, useReview, useReviewCommand, useReviewWorkspace } from "../../entities/review";
import type { ReviewAttempt, ReviewItem, ReviewMaskStroke } from "../../entities/review";
import { endpoints, queryKeys } from "../../shared/api";
import { useReviewWorkbenchStore } from "./store";
import { TopBar } from "./TopBar";
import { ToolRail } from "./ToolRail";
import { CanvasViewer, type ReviewMapHandle } from "./CanvasViewer";
import { CategoryPanel } from "./CategoryPanel";
import { ObjectList } from "./ObjectList";
import { ItemInspector } from "./ItemInspector";
import { TiffInfoPanel } from "./TiffInfoPanel";
import { ObjectThumbnailBar } from "./ObjectThumbnailBar";
import { StatusBar } from "./StatusBar";
import { PromptPanel } from "./PromptPanel";
import { AttemptPanel } from "./AttemptPanel";
import { MaskEditor } from "./MaskEditor";
import "./ReviewWorkbench.css";

const CATEGORY_COLORS = ["#72bc8f", "#5e9fe8", "#eac26b", "#bf8eda", "#de9255", "#df84a8", "#4fb9c9", "#e97366"];

export function ReviewWorkbench({ sessionId }: { sessionId: string }) {
  const navigate = useNavigate();
  const client = useQueryClient();
  const session = useReview(sessionId);
  const workspace = useReviewWorkspace(sessionId);
  const mapContext = useQuery({ queryKey: ["review-map-context", sessionId], queryFn: () => endpoints.getReviewMapContext(sessionId) });
  const command = useReviewCommand(sessionId);
  const mapRef = useRef<ReviewMapHandle>(null);
  const store = useReviewWorkbenchStore();
  const [attempts, setAttempts] = useState<ReviewAttempt[]>([]);
  const [candidateItems, setCandidateItems] = useState<ReviewItem[]>([]);
  const [editingMask, setEditingMask] = useState<ReviewItem | null>(null);
  const [helpModalOpen, setHelpModalOpen] = useState(false);
  const [effectiveAreaVisible, setEffectiveAreaVisible] = useState(false);
  const [basemapId, setBasemapId] = useState("satellite");
  const [roadOverlay, setRoadOverlay] = useState(false);

  useEffect(() => {
    if (!workspace.data) return;
    store.hydrate(workspace.data);
    setAttempts(workspace.data.attempts);
  }, [workspace.data?.revision]);

  const items = useMemo(() => store.order.map((id) => store.itemsById[id]).filter(Boolean), [store.itemsById, store.order]);
  const active = store.activeId ? store.itemsById[store.activeId] : undefined;
  const categories = workspace.data?.category_catalog ?? [];
  const visibleItems = items.filter((item) => !store.hiddenCategories.includes(item.species));

  const apply = useCallback(async (operations: Array<Record<string, unknown>>, prefix = "edit") => {
    if (!operations.length) return;
    store.setIsSyncing(true);
    try {
      const patch = await command.mutateAsync({ revision: store.revision, operation_id: operationId(prefix), operations });
      store.applyPatch(patch);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "操作提交失败");
    } finally {
      store.setIsSyncing(false);
    }
  }, [command, store.revision]);

  const editableIds = useCallback((ids: string[]) => ids.filter((id) => !store.itemsById[id]?.frozen), [store.itemsById]);
  const deleteItems = useCallback(async (ids: string[]) => {
    const editable = editableIds(ids);
    if (editable.length < ids.length) message.warning("冻结框已保留；只能删除本轮可编辑框");
    await apply(editable.map((id) => ({ type: "delete", item_id: id })), "delete");
  }, [apply, editableIds]);

  const history = useMutation({
    mutationFn: (kind: "undo" | "redo") => kind === "undo" ? endpoints.undoReview(sessionId, store.revision, operationId(kind)) : endpoints.redoReview(sessionId, store.revision, operationId(kind)),
    onSuccess: (patch) => {
      store.applyPatch(patch);
      client.setQueryData(queryKeys.reviewWorkspace(sessionId), (current: unknown) => ({ ...((current as Record<string, unknown>) ?? {}), revision: patch.revision, items: patch.items }));
    },
    onError: (error) => message.error(error instanceof Error ? error.message : "历史操作失败"),
  });
  const publish = useMutation({
    mutationFn: () => endpoints.publishReview(sessionId),
    onSuccess: (result) => {
      message.success(`发布成功，已生成 review run ${result.run_id}`);
      void client.invalidateQueries({ queryKey: queryKeys.reviews });
      void client.invalidateQueries({ queryKey: queryKeys.assets });
      navigate("/review", { replace: true });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : "发布失败"),
  });
  const saveMask = useMutation({
    mutationFn: ({ itemId, strokes }: { itemId: string; strokes: ReviewMaskStroke[] }) => endpoints.applyReviewMask(sessionId, { revision: store.revision, operation_id: operationId("mask"), item_id: itemId, strokes }),
    onSuccess: (patch) => { store.applyPatch(patch); setEditingMask(null); message.success("实例 Mask 已保存"); },
    onError: (error) => message.error(error instanceof Error ? error.message : "Mask 保存失败"),
  });

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest("input,textarea,[contenteditable=true],.ant-select")) return;
      const key = event.key.toLowerCase();
      if ((event.ctrlKey || event.metaKey) && key === "z") { event.preventDefault(); history.mutate(event.shiftKey ? "redo" : "undo"); return; }
      if ((event.ctrlKey || event.metaKey) && key === "y") { event.preventDefault(); history.mutate("redo"); return; }
      if ((event.key === "Delete" || event.key === "Backspace") && store.selectedIds.length) { event.preventDefault(); void deleteItems(store.selectedIds); return; }
      if (event.key === "Escape") { store.clearSelection(); return; }
      if (key === "v") store.setActiveTool("select");
      else if (key === "h") store.setActiveTool("pan");
      else if (key === "r") store.setActiveTool("draw");
      else if (key === "t") store.setActiveTool("ai_text");
      else if (key === "i") store.setActiveTool("ai_visual");
      else if (/^[1-9]$/.test(key)) {
        const category = categories[Number(key) - 1];
        if (category) store.setActiveCategory(category.id);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [categories, deleteItems, history, store.selectedIds]);

  if (session.isLoading || workspace.isLoading || mapContext.isLoading) return <div className="review-loading"><Spin size="large" tip="加载与恢复单 TIFF 复核会话…" /></div>;
  if (!session.data || !workspace.data || !mapContext.data || session.isError || workspace.isError || mapContext.isError) {
    return <div className="review-loading"><Empty description={mapContext.error instanceof Error ? mapContext.error.message : "无法加载该复核会话"} /></div>;
  }

  const setCatalog = async (next: typeof categories, activeCategory = store.activeCategory) => {
    await apply([{ type: "set_catalog", categories: next, active_category: activeCategory }], "catalog");
    await client.invalidateQueries({ queryKey: queryKeys.reviewWorkspace(sessionId) });
  };
  const categoryAction = (id: string, action: "accept" | "reject" | "delete") => {
    const targets = items.filter((item) => item.species === id).map((item) => item.id);
    if (action === "delete") { void deleteItems(targets); return; }
    void apply([{ type: "bulk_status", item_ids: targets, status: action === "accept" ? "accepted" : "rejected" }], "category-status");
  };
  const updateSelectedCategory = (species: string) => {
    const targets = editableIds(store.selectedIds);
    if (targets.length < store.selectedIds.length) message.warning("冻结框的树种不会被修改");
    void apply(targets.map((id) => ({ type: "set_category", item_id: id, species })), "bulk-category");
  };

  return (
    <div className="review-workbench-root">
      <div className="area-topbar"><TopBar session={session.data} onPublish={() => publish.mutate()} isPublishing={publish.isPending} /></div>
      <div className="area-toolrail">
        <ToolRail
          canUndo
          canRedo
          basemapId={basemapId}
          roadOverlay={roadOverlay}
          onUndo={() => history.mutate("undo")}
          onRedo={() => history.mutate("redo")}
          onDeleteSelected={() => void deleteItems(store.selectedIds)}
          onClearWorkspace={() => Modal.confirm({ title: "清空可编辑工作集？", content: "冻结框将保留，其余对象会被删除。", okText: "清空", okButtonProps: { danger: true }, cancelText: "取消", onOk: () => deleteItems(items.map((item) => item.id)) })}
          onFitViewport={() => mapRef.current?.fitViewport()}
          onZoomIn={() => mapRef.current?.zoomIn()}
          onZoomOut={() => mapRef.current?.zoomOut()}
          onResetNorth={() => mapRef.current?.resetNorth()}
          onToggleEffectiveArea={() => setEffectiveAreaVisible((value) => !value)}
          onBasemapChange={(value) => { setBasemapId(value); mapRef.current?.setBasemap(value); }}
          onRoadOverlayChange={(value) => { setRoadOverlay(value); mapRef.current?.setRoadOverlay(value); }}
          onOpenHelp={() => setHelpModalOpen(true)}
        />
      </div>
      <div className="area-stage">
        <div className="stage-canvas-wrap">
          <CanvasViewer
            ref={mapRef}
            mapContext={mapContext.data}
            tileUrl={endpoints.reviewTileUrl(session.data.phase_id, session.data.tiff_id)}
            items={items}
            candidateItems={candidateItems}
            categories={categories}
            effectiveAreaVisible={effectiveAreaVisible}
            onSelect={(id, additive) => store.select(id, additive)}
            onSelectMany={store.setSelectedIds}
            onAddBox={(boxPx) => {
              const species = store.activeCategory || categories[0]?.id;
              if (!species) { message.warning("请先创建并选择树种类别"); return; }
              void apply([{ type: "add", item: { box_px: boxPx, species } }], "add");
            }}
            onUpdateBox={(id, boxPx) => void apply([{ type: "update", item_id: id, patch: { box_px: boxPx } }], "resize")}
          />
          {store.selectedIds.length ? (
            <div className="review-bulk-floating">
              <Typography.Text strong>已选 {store.selectedIds.length} 个对象</Typography.Text>
              <Select size="small" placeholder="修改类别" options={categories.map((category) => ({ value: category.id, label: category.display_name }))} onChange={updateSelectedCategory} style={{ width: 140 }} />
              <Button size="small" type="primary" icon={<CheckOutlined />} onClick={() => void apply([{ type: "bulk_status", item_ids: store.selectedIds, status: "accepted" }], "bulk-status")}>接受</Button>
              <Button size="small" icon={<CloseOutlined />} onClick={() => void apply([{ type: "bulk_status", item_ids: store.selectedIds, status: "rejected" }], "bulk-status")}>拒绝</Button>
              <Button size="small" danger icon={<DeleteOutlined />} onClick={() => void deleteItems(store.selectedIds)}>删除</Button>
            </div>
          ) : null}
          <PromptPanel sessionId={sessionId} revision={store.revision} categories={categories} items={items} mapContext={mapContext.data} getCenterPx={() => mapRef.current?.getCenterPx() ?? null} onCreated={(attempt) => setAttempts((current) => [...current.filter((item) => item.attempt_id !== attempt.attempt_id), attempt])} />
          <AttemptPanel sessionId={sessionId} revision={store.revision} attempts={attempts} mergeMode={store.mergeMode} onChanged={(attempt) => setAttempts((current) => [...current.filter((item) => item.attempt_id !== attempt.attempt_id), attempt])} onPreview={setCandidateItems} onApplied={(revision, nextItems) => store.replaceItems(revision, nextItems)} />
        </div>
        <ObjectThumbnailBar items={items} categories={categories} onSelect={(id) => store.select(id)} />
      </div>
      <div className="area-panel">
        <Tabs defaultActiveKey="objects" size="small" className="review-side-tabs" items={[
          { key: "objects", label: "标注对象", children: <div className="review-object-pane"><CategoryPanel categories={categories} items={items} freshMode={session.data.mode === "fresh"} onAddCategory={(name) => { const next = [...categories, { id: name, display_name: name, model_prompt: name, color: CATEGORY_COLORS[categories.length % CATEGORY_COLORS.length] }]; void setCatalog(next, name); }} onChangeColor={(id, color) => void setCatalog(categories.map((category) => category.id === id ? { ...category, color } : category))} onCategoryAction={categoryAction} /><ObjectList items={items} categories={categories} onSelect={(id, additive) => store.select(id, additive)} onBulkStatus={(status) => void apply([{ type: "bulk_status", item_ids: store.selectedIds, status }], "bulk-status")} onBulkDelete={() => void deleteItems(store.selectedIds)} /></div> },
          { key: "inspector", label: "属性编辑", children: active ? <ItemInspector item={active} categories={categories} busy={command.isPending} onUpdate={(patch) => apply([{ type: "update", item_id: active.id, patch }], "item")} onDelete={() => deleteItems([active.id])} onEditMask={active.mask_rle && !active.frozen ? () => setEditingMask(active) : undefined} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未选中任何对象" /> },
          { key: "meta", label: "影像信息", children: <TiffInfoPanel session={session.data} /> },
        ]} />
      </div>
      <div className="area-statusbar"><StatusBar totalItems={items.length} visibleItems={visibleItems.length} /></div>
      <MaskEditor open={Boolean(editingMask)} item={editingMask} saving={saveMask.isPending} onCancel={() => setEditingMask(null)} onSave={async (strokes) => { if (editingMask) await saveMask.mutateAsync({ itemId: editingMask.id, strokes }); }} />
      <Modal title="工作台快捷键" open={helpModalOpen} footer={null} onCancel={() => setHelpModalOpen(false)}>
        <div className="review-shortcuts"><span><kbd>V</kbd> 选择 / 框选</span><span><kbd>H</kbd> 平移地图</span><span><kbd>R</kbd> 手动画框</span><span><kbd>T</kbd> AI 文本</span><span><kbd>I</kbd> AI 视觉</span><span><kbd>1–9</kbd> 切换树种</span><span><kbd>Ctrl/⌘ Z</kbd> 撤销</span><span><kbd>Delete</kbd> 删除可编辑框</span></div>
      </Modal>
    </div>
  );
}
