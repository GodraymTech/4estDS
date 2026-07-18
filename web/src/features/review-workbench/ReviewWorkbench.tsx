import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Empty,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Spin,
  Statistic,
  Tag,
  Tooltip,
  message,
} from "antd";
import {
  CheckOutlined,
  CloseOutlined,
  DeleteOutlined,
  PlusOutlined,
  RedoOutlined,
  SaveOutlined,
  UndoOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { operationId, useReview, useReviewCommand, useReviewWorkspace } from "../../entities/review";
import type { ReviewCategory, ReviewItem } from "../../entities/review";
import { endpoints, queryKeys } from "../../shared/api";
import { useReviewWorkbenchStore } from "./store";
import "./ReviewWorkbench.css";

export function ReviewWorkbench({ sessionId }: { sessionId: string }) {
  const navigate = useNavigate();
  const client = useQueryClient();
  const session = useReview(sessionId);
  const workspace = useReviewWorkspace(sessionId);
  const tiffs = useQuery({ queryKey: queryKeys.tiffs, queryFn: endpoints.listTiffs });
  const command = useReviewCommand(sessionId);
  const store = useReviewWorkbenchStore();
  const [filter, setFilter] = useState<string>("all");
  const [newCategory, setNewCategory] = useState("");

  const dimensions = useMemo(() => {
    const tiff = tiffs.data?.find((item) => item.phase_id === session.data?.phase_id && item.tiff_id === session.data?.tiff_id);
    return { width: tiff?.pixel_width || 1, height: tiff?.pixel_height || 1 };
  }, [session.data, tiffs.data]);

  useEffect(() => {
    if (workspace.data) store.hydrate(workspace.data);
  }, [workspace.data?.revision]);

  const items = useMemo(
    () => store.order.map((id) => store.itemsById[id]).filter(Boolean),
    [store.itemsById, store.order],
  );
  const visible = useMemo(
    () => items.filter((item) => filter === "all" || item.status === filter || (filter === "conflict" && item.conflict)),
    [filter, items],
  );
  const active = store.activeId ? store.itemsById[store.activeId] : undefined;
  const categories = workspace.data?.category_catalog ?? [];

  const apply = useCallback(async (operations: Array<Record<string, unknown>>, prefix = "edit") => {
    const patch = await command.mutateAsync({ revision: store.revision, operation_id: operationId(prefix), operations });
    store.replaceItems(patch.revision, patch.items);
  }, [command, sessionId, store.revision]);

  const history = useMutation({
    mutationFn: async (kind: "undo" | "redo") => {
      const id = operationId(kind);
      return kind === "undo"
        ? endpoints.undoReview(sessionId, store.revision, id)
        : endpoints.redoReview(sessionId, store.revision, id);
    },
    onSuccess: (patch) => {
      store.replaceItems(patch.revision, patch.items);
      client.setQueryData(queryKeys.reviewWorkspace(sessionId), (current: unknown) => ({
        ...(current as Record<string, unknown> ?? {}), revision: patch.revision, items: patch.items,
      }));
    },
    onError: (error) => message.error(error instanceof Error ? error.message : "历史操作失败"),
  });

  const publish = useMutation({
    mutationFn: () => endpoints.publishReview(sessionId),
    onSuccess: (result) => {
      message.success(`已发布 review run ${result.run_id}`);
      void client.invalidateQueries({ queryKey: queryKeys.reviews });
      void client.invalidateQueries({ queryKey: queryKeys.assets });
      navigate("/review", { replace: true });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : "发布失败"),
  });

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
      } else if ((event.key === "Delete" || event.key === "Backspace") && store.activeId) {
        event.preventDefault();
        void apply([{ type: "delete", item_id: store.activeId }], "delete");
      } else if (event.key === "Escape") {
        store.clearSelection();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [apply, history, store.activeId]);

  if (session.isLoading || workspace.isLoading) return <div className="review-loading"><Spin tip="恢复复核草稿" /></div>;
  if (!session.data || !workspace.data || session.isError || workspace.isError) {
    return <div className="review-loading"><Empty description="复核会话加载失败" /><Button onClick={() => navigate("/review")}>返回</Button></div>;
  }

  const summary = {
    total: items.filter((item) => item.status !== "rejected").length,
    accepted: items.filter((item) => item.status === "accepted").length,
    rejected: items.filter((item) => item.status === "rejected").length,
    conflicts: items.filter((item) => item.conflict).length,
  };

  return (
    <div className="review-workbench">
      <header className="review-workbench__topbar">
        <div>
          <strong>单 TIFF 智能复核</strong>
          <span>{session.data.phase_id} / {session.data.tiff_id}</span>
          <Tag color="cyan">rev {store.revision}</Tag>
          <Tag>{session.data.mode === "based_on_active" ? `基于 ${session.data.base_run_id}` : "从 0 开始"}</Tag>
        </div>
        <Space>
          <Tooltip title="Ctrl/⌘ + Z"><Button icon={<UndoOutlined />} loading={history.isPending} onClick={() => history.mutate("undo")}>撤销</Button></Tooltip>
          <Tooltip title="Ctrl/⌘ + Y"><Button icon={<RedoOutlined />} loading={history.isPending} onClick={() => history.mutate("redo")}>重做</Button></Tooltip>
          <Button onClick={() => navigate("/review")}>返回草稿</Button>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            loading={publish.isPending}
            disabled={summary.conflicts > 0}
            onClick={() => Modal.confirm({
              title: "发布为当前 TIFF 正式结果？",
              content: `将创建 review run，并原子发布 ${summary.total} 个对象。父 run 不会被修改。`,
              okText: "确认发布",
              onOk: () => publish.mutateAsync(),
            })}
          >发布</Button>
        </Space>
      </header>

      <aside className="review-workbench__left">
        <div className="review-workbench__stats">
          <Statistic title="预计结果" value={summary.total} />
          <Statistic title="接受" value={summary.accepted} />
          <Statistic title="拒绝" value={summary.rejected} />
          <Statistic title="冲突" value={summary.conflicts} valueStyle={{ color: summary.conflicts ? "#ff7875" : undefined }} />
        </div>
        <Select
          value={filter}
          style={{ width: "100%" }}
          options={[
            { value: "all", label: "全部对象" },
            { value: "accepted", label: "已接受" },
            { value: "pending", label: "待确认" },
            { value: "rejected", label: "已拒绝" },
            { value: "conflict", label: "冲突" },
          ]}
          onChange={setFilter}
        />
        <div className="review-workbench__batch">
          <Button size="small" icon={<CheckOutlined />} disabled={!store.selectedIds.length} onClick={() => apply([{ type: "bulk_status", item_ids: store.selectedIds, status: "accepted" }], "accept")}>接受</Button>
          <Button size="small" icon={<CloseOutlined />} disabled={!store.selectedIds.length} onClick={() => apply([{ type: "bulk_status", item_ids: store.selectedIds, status: "rejected" }], "reject")}>拒绝</Button>
        </div>
        <div className="review-workbench__list">
          {visible.map((item) => (
            <button
              key={item.id}
              type="button"
              className={store.activeId === item.id ? "is-active" : ""}
              onClick={(event) => store.select(item.id, event.ctrlKey || event.metaKey)}
            >
              <span aria-hidden>{store.selectedIds.includes(item.id) ? "☑" : "☐"}</span>
              <span>{item.species || "未分类"}</span>
              <Tag color={item.status === "rejected" ? "red" : item.status === "pending" ? "gold" : "green"}>{item.status}</Tag>
            </button>
          ))}
        </div>
      </aside>

      <main className="review-workbench__stage">
        <div className="review-workbench__image-wrap">
          <img src={endpoints.reviewPreviewUrl(sessionId)} alt="当前复核 TIFF 降采样预览" draggable={false} />
          <div className="review-workbench__boxes">
            {visible.filter((item) => item.status !== "rejected").map((item) => (
              <BoxOverlay
                key={item.id}
                item={item}
                width={dimensions.width}
                height={dimensions.height}
                selected={store.activeId === item.id}
                color={categoryColor(categories, item.species)}
                onClick={(event) => { event.stopPropagation(); store.select(item.id, event.ctrlKey || event.metaKey); }}
              />
            ))}
          </div>
        </div>
        <Button
          className="review-workbench__add"
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => apply([{
            type: "add",
            item: {
              box_px: [dimensions.width * 0.4, dimensions.height * 0.4, dimensions.width * 0.6, dimensions.height * 0.6],
              species: categories[0]?.id ?? "",
            },
          }], "add")}
        >新建人工框</Button>
      </main>

      <aside className="review-workbench__right">
        <section>
          <h3>类别目录</h3>
          <Space.Compact block>
            <Input value={newCategory} placeholder="新增树种" onChange={(event) => setNewCategory(event.target.value)} />
            <Button onClick={() => {
              const name = newCategory.trim();
              if (!name) return;
              const next = [...categories, { id: name, display_name: name, model_prompt: name, color: autoColor(categories.length) }];
              void apply([{ type: "set_catalog", categories: next, active_category: name }], "catalog");
              setNewCategory("");
            }}>添加</Button>
          </Space.Compact>
          <div className="review-workbench__categories">
            {categories.map((category) => <Tag color={category.color} key={category.id}>{category.display_name}</Tag>)}
          </div>
        </section>

        <section>
          <h3>当前对象</h3>
          {active ? (
            <ItemInspector
              item={active}
              categories={categories}
              busy={command.isPending}
              onUpdate={(patch) => apply([{ type: "update", item_id: active.id, patch }], "item")}
              onDelete={() => apply([{ type: "delete", item_id: active.id }], "delete")}
            />
          ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择一个框" />}
        </section>
        {summary.conflicts ? <Alert type="error" showIcon message="发布前需解决全部冲突" /> : null}
      </aside>

      <footer className="review-workbench__status">
        <span>工作集 {items.length}</span><span>显示 {visible.length}</span><span>选择 {store.selectedIds.length}</span>
        <span>{command.isPending ? "正在写入服务端草稿…" : "草稿已恢复并同步"}</span>
      </footer>
    </div>
  );
}

function BoxOverlay({ item, width, height, selected, color, onClick }: {
  item: ReviewItem; width: number; height: number; selected: boolean; color: string;
  onClick: (event: React.MouseEvent<HTMLButtonElement>) => void;
}) {
  const [x1, y1, x2, y2] = item.box_px;
  return (
    <button
      type="button"
      aria-label={`${item.species || "未分类"} 检测框`}
      className={selected ? "review-box is-selected" : "review-box"}
      style={{ left: `${x1 / width * 100}%`, top: `${y1 / height * 100}%`, width: `${(x2 - x1) / width * 100}%`, height: `${(y2 - y1) / height * 100}%`, borderColor: color }}
      onClick={onClick}
    ><span style={{ background: color }}>{item.species || "未分类"}</span></button>
  );
}

function ItemInspector({ item, categories, busy, onUpdate, onDelete }: {
  item: ReviewItem; categories: ReviewCategory[]; busy: boolean;
  onUpdate: (patch: Record<string, unknown>) => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  const [box, setBox] = useState(item.box_px);
  const [note, setNote] = useState(item.note ?? "");
  useEffect(() => { setBox(item.box_px); setNote(item.note ?? ""); }, [item.id, item.box_px.join(","), item.note]);
  return (
    <div className="review-workbench__inspector-form">
      <Select value={item.species || undefined} placeholder="必须选择类别" options={categories.map((value) => ({ value: value.id, label: value.display_name }))} onChange={(species) => onUpdate({ species })} />
      <div className="review-workbench__coords">
        {box.map((value, index) => <InputNumber key={index} value={value} min={0} onChange={(next) => setBox(box.map((old, at) => at === index ? Number(next ?? old) : old))} />)}
      </div>
      <Button disabled={busy || box.join(",") === item.box_px.join(",")} onClick={() => onUpdate({ box_px: box })}>应用框坐标</Button>
      <Input.TextArea value={note} placeholder="复核备注" autoSize={{ minRows: 2, maxRows: 5 }} onChange={(event) => setNote(event.target.value)} onBlur={() => { if (note !== (item.note ?? "")) void onUpdate({ note }); }} />
      <Select value={item.status} options={[{ value: "accepted", label: "接受" }, { value: "pending", label: "待确认" }, { value: "rejected", label: "拒绝" }]} onChange={(status) => onUpdate({ status })} />
      <Button danger icon={<DeleteOutlined />} onClick={onDelete}>删除对象</Button>
    </div>
  );
}

function categoryColor(categories: ReviewCategory[], species: string): string {
  return categories.find((item) => item.id === species)?.color ?? "#ffffff";
}

function autoColor(index: number): string {
  return ["#52c99a", "#69b1ff", "#ffc53d", "#ff7a45", "#b37feb", "#36cfc9"][index % 6];
}
