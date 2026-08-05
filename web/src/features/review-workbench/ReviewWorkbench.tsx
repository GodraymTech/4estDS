import { useCallback, useEffect, useMemo, useState } from "react";
import { Drawer, Empty, Modal, Spin, Tabs, message } from "antd";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { operationId, useReview, useReviewCommand, useReviewWorkspace } from "../../entities/review";
import type { ReviewAttempt, ReviewItem, ReviewMaskStroke } from "../../entities/review";
import { endpoints, queryKeys } from "../../shared/api";
import { useReviewWorkbenchStore } from "./store";

import { TopBar } from "./TopBar";
import { ToolRail } from "./ToolRail";
import { CanvasViewer } from "./CanvasViewer";
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

export function ReviewWorkbench({ sessionId }: { sessionId: string }) {
  const navigate = useNavigate();
  const client = useQueryClient();
  const session = useReview(sessionId);
  const workspace = useReviewWorkspace(sessionId);
  const command = useReviewCommand(sessionId);
  const store = useReviewWorkbenchStore();

  const [attempts, setAttempts] = useState<ReviewAttempt[]>([]);
  const [editingMask, setEditingMask] = useState<ReviewItem | null>(null);
  const [promptDrawerOpen, setPromptDrawerOpen] = useState(false);
  const [helpModalOpen, setHelpModalOpen] = useState(false);

  useEffect(() => {
    if (workspace.data) {
      store.hydrate(workspace.data);
      setAttempts(workspace.data.attempts);
    }
  }, [workspace.data?.revision]);

  const items = useMemo(
    () => store.order.map((id) => store.itemsById[id]).filter(Boolean),
    [store.itemsById, store.order]
  );

  const active = store.activeId ? store.itemsById[store.activeId] : undefined;
  const categories = workspace.data?.category_catalog ?? [];

  const apply = useCallback(
    async (operations: Array<Record<string, unknown>>, prefix = "edit") => {
      store.setIsSyncing(true);
      try {
        const patch = await command.mutateAsync({
          revision: store.revision,
          operation_id: operationId(prefix),
          operations,
        });
        store.applyPatch(patch);
      } catch (err) {
        message.error(err instanceof Error ? err.message : "操作提交失败");
      } finally {
        store.setIsSyncing(false);
      }
    },
    [command, store]
  );

  const history = useMutation({
    mutationFn: async (kind: "undo" | "redo") => {
      const id = operationId(kind);
      return kind === "undo"
        ? endpoints.undoReview(sessionId, store.revision, id)
        : endpoints.redoReview(sessionId, store.revision, id);
    },
    onSuccess: (patch) => {
      store.applyPatch(patch);
      client.setQueryData(queryKeys.reviewWorkspace(sessionId), (current: unknown) => ({
        ...((current as Record<string, unknown>) ?? {}),
        revision: patch.revision,
        items: patch.items,
      }));
    },
    onError: (error) => message.error(error instanceof Error ? error.message : "历史操作失败"),
  });

  const publish = useMutation({
    mutationFn: () => endpoints.publishReview(sessionId),
    onSuccess: (result) => {
      message.success(`发布成功！已生成 review run ${result.run_id}`);
      void client.invalidateQueries({ queryKey: queryKeys.reviews });
      void client.invalidateQueries({ queryKey: queryKeys.assets });
      navigate("/review", { replace: true });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : "发布失败"),
  });

  const saveMask = useMutation({
    mutationFn: ({ itemId, strokes }: { itemId: string; strokes: ReviewMaskStroke[] }) =>
      endpoints.applyReviewMask(sessionId, {
        revision: store.revision,
        operation_id: operationId("mask"),
        item_id: itemId,
        strokes,
      }),
    onSuccess: (patch) => {
      store.applyPatch(patch);
      client.setQueryData(queryKeys.reviewWorkspace(sessionId), (current: unknown) => ({
        ...((current as Record<string, unknown>) ?? {}),
        revision: patch.revision,
        items: patch.items,
      }));
      setEditingMask(null);
      message.success("实例 Mask 已成功保存");
    },
    onError: (error) => message.error(error instanceof Error ? error.message : "Mask 保存失败"),
  });

  // 全局快捷键处理
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest("input,textarea,[contenteditable=true]")) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        history.mutate(event.shiftKey ? "redo" : "undo");
      } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") {
        event.preventDefault();
        history.mutate("redo");
      } else if ((event.key === "Delete" || event.key === "Backspace") && store.selectedIds.length > 0) {
        event.preventDefault();
        void apply(
          store.selectedIds.map((id) => ({ type: "delete", item_id: id })),
          "delete"
        );
      } else if (event.key === "Escape") {
        store.clearSelection();
      } else if (event.key.toLowerCase() === "v") {
        store.setActiveTool("select");
      } else if (event.key.toLowerCase() === "r") {
        store.setActiveTool("draw");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [apply, history, store]);

  if (session.isLoading || workspace.isLoading) {
    return (
      <div className="review-loading">
        <Spin size="large" tip="加载与恢复单 TIFF 复核会话..." />
      </div>
    );
  }

  if (!session.data || !workspace.data || session.isError || workspace.isError) {
    return (
      <div className="review-loading">
        <Empty description="无法加载该复核会话" />
      </div>
    );
  }

  return (
    <div className="review-workbench-root">
      {/* 顶栏 */}
      <div className="area-topbar">
        <TopBar
          session={session.data}
          canUndo={true}
          canRedo={true}
          onUndo={() => history.mutate("undo")}
          onRedo={() => history.mutate("redo")}
          onPublish={() => publish.mutateAsync()}
          isPublishing={publish.isPending}
        />
      </div>

      {/* 左侧垂直工具栏 */}
      <div className="area-toolrail">
        <ToolRail
          canUndo={true}
          canRedo={true}
          onUndo={() => history.mutate("undo")}
          onRedo={() => history.mutate("redo")}
          onDeleteSelected={() =>
            apply(
              store.selectedIds.map((id) => ({ type: "delete", item_id: id })),
              "delete"
            )
          }
          onOpenPrompt={() => setPromptDrawerOpen(true)}
          onOpenHelp={() => setHelpModalOpen(true)}
        />
      </div>

      {/* 中央舞台 (Canvas Viewer + 底部缩略图条) */}
      <div className="area-stage">
        <div className="stage-canvas-wrap">
          <CanvasViewer
            previewUrl={endpoints.reviewPreviewUrl(sessionId)}
            items={items}
            categories={categories}
            onSelect={(id, additive) => store.select(id, additive)}
            onAddBox={(boxPx) =>
              apply(
                [
                  {
                    type: "add",
                    item: {
                      box_px: boxPx,
                      species: store.activeCategory || categories[0]?.id || "",
                    },
                  },
                ],
                "add"
              )
            }
            onUpdateBox={(id, boxPx) =>
              apply([{ type: "update", item_id: id, patch: { box_px: boxPx } }], "resize")
            }
          />
        </div>

        <ObjectThumbnailBar
          items={items}
          categories={categories}
          onSelect={(id) => store.select(id)}
        />
      </div>

      {/* 右侧面板 */}
      <div className="area-panel">
        <Tabs
          defaultActiveKey="objects"
          size="small"
          style={{ height: "100%", display: "flex", flexDirection: "column" }}
          items={[
            {
              key: "objects",
              label: "标注对象",
              children: (
                <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
                  <CategoryPanel
                    categories={categories}
                    items={items}
                    onAddCategory={(name) => {
                      const next = [
                        ...categories,
                        { id: name, display_name: name, model_prompt: name, color: "#52c99a" },
                      ];
                      void apply([{ type: "set_catalog", categories: next, active_category: name }], "catalog");
                    }}
                    onChangeColor={(id, color) => {
                      const next = categories.map((c) => (c.id === id ? { ...c, color } : c));
                      void apply([{ type: "set_catalog", categories: next, active_category: store.activeCategory }], "color");
                    }}
                  />
                  <ObjectList
                    items={items}
                    categories={categories}
                    onSelect={(id, additive) => store.select(id, additive)}
                    onBulkStatus={(status) =>
                      apply(
                        [{ type: "bulk_status", item_ids: store.selectedIds, status }],
                        "bulk_status"
                      )
                    }
                    onBulkDelete={() =>
                      apply(
                        store.selectedIds.map((id) => ({ type: "delete", item_id: id })),
                        "delete"
                      )
                    }
                  />
                </div>
              ),
            },
            {
              key: "inspector",
              label: "属性编辑",
              children: active ? (
                <ItemInspector
                  item={active}
                  categories={categories}
                  busy={command.isPending}
                  onUpdate={(patch) => apply([{ type: "update", item_id: active.id, patch }], "item")}
                  onDelete={() => apply([{ type: "delete", item_id: active.id }], "delete")}
                  onEditMask={active.mask_rle ? () => setEditingMask(active) : undefined}
                />
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未选中任何对象" />
              ),
            },
            {
              key: "meta",
              label: "影像信息",
              children: <TiffInfoPanel session={session.data} />,
            },
          ]}
        />
      </div>

      {/* 底栏 */}
      <div className="area-statusbar">
        <StatusBar totalItems={items.length} visibleItems={items.length} />
      </div>

      {/* AI 交互式检测 Drawer */}
      <Drawer
        title="AI 智能辅助标框 (Text & Visual Prompt)"
        placement="right"
        width={400}
        onClose={() => setPromptDrawerOpen(false)}
        open={promptDrawerOpen}
      >
        <PromptPanel
          sessionId={sessionId}
          revision={store.revision}
          categories={categories}
          items={items}
          onCreated={(attempt) =>
            setAttempts((current) => [...current.filter((item) => item.attempt_id !== attempt.attempt_id), attempt])
          }
        />
        <AttemptPanel
          sessionId={sessionId}
          revision={store.revision}
          attempts={attempts}
          onChanged={(attempt) =>
            setAttempts((current) => [...current.filter((item) => item.attempt_id !== attempt.attempt_id), attempt])
          }
          onApplied={(revision, nextItems) => store.replaceItems(revision, nextItems)}
        />
      </Drawer>

      {/* Mask 弹窗编辑器 */}
      <MaskEditor
        open={Boolean(editingMask)}
        item={editingMask}
        saving={saveMask.isPending}
        onCancel={() => setEditingMask(null)}
        onSave={async (strokes) => {
          if (editingMask) await saveMask.mutateAsync({ itemId: editingMask.id, strokes });
        }}
      />

      {/* 快捷键帮助 Modal */}
      <Modal
        title="工作台快捷键指南"
        open={helpModalOpen}
        footer={null}
        onCancel={() => setHelpModalOpen(false)}
      >
        <ul>
          <li><strong>V</strong>: 选择与平移工具</li>
          <li><strong>R</strong>: 手动画框工具</li>
          <li><strong>T</strong>: 打开 AI 文本提示面板</li>
          <li><strong>I</strong>: 打开 AI 视觉样例面板</li>
          <li><strong>Ctrl + Z / ⌘ + Z</strong>: 撤销上一步操作</li>
          <li><strong>Ctrl + Y / ⌘ + Y</strong>: 重做操作</li>
          <li><strong>Delete / Backspace</strong>: 删除选中的检测框</li>
          <li><strong>Space + 拖拽</strong> 或 <strong>鼠标中键</strong>: 移动/平移画布</li>
          <li><strong>鼠标滚轮</strong>: 以指针中心缩放画布</li>
        </ul>
      </Modal>
    </div>
  );
}
