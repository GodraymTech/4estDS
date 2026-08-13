import { useEffect, useMemo, useState } from "react";
import { Button, Empty, Modal, Popconfirm, Segmented, Table, Tag, Tooltip, message } from "antd";
import type { TableProps } from "antd";
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  CloseOutlined,
  EditOutlined,
  ExportOutlined,
  PoweroffOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { endpoints, queryKeys, type JobHistoryItem, type JobState, type JobStatus } from "../../shared/api";
import { useJob } from "../../entities/run";
import { UploadForm } from "./UploadForm";
import { JobStatusCell } from "./JobStatusCell";
import { useJobsStore, type PendingTask, type SubmittedJob } from "./jobsStore";
import "./TasksCenter.css";

// 一次提交会产生一个顶层 batch run 与 N 个 infer 子 run，两者都要进历史列表。
const JOB_TASK_TYPES = "infer,batch";
const JOB_TASK_TYPES_WITH_REVIEW = "infer,batch,review";

const TABLE_LOCALE = { emptyText: <Empty description="暂无作业" /> };
const PENDING_LOCALE = {
  emptyText: <Empty description="暂无待命条目，在左侧填好参数后点「加入队列」" />,
};

const STATUS_TEXT: Record<JobState, string> = {
  queued: "排队中",
  running: "推理中",
  succeeded: "已完成",
  failed: "失败",
  canceled: "已取消",
};

/** 批量作业明细条目(对应后端 metrics.items)。 */
interface BatchItemRow {
  path?: string;
  tract_key?: string;
  status?: string;
  run_id?: string;
  tree_count?: number;
  error?: string;
}

const ITEM_STATUS: Record<string, { color: string; text: string }> = {
  succeeded: { color: "success", text: "完成" },
  failed: { color: "error", text: "失败" },
  canceled: { color: "default", text: "已取消" },
};

type QueueView = "pending" | "submitted";

export function TasksCenter() {
  const submitted = useJobsStore((s) => s.submitted);
  const pending = useJobsStore((s) => s.pending);
  const [activeJobId, setActiveJobId] = useState<string | undefined>(submitted[0]?.jobId);
  const [queueView, setQueueView] = useState<QueueView>(pending.length ? "pending" : "submitted");
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!activeJobId && submitted[0]?.jobId) setActiveJobId(submitted[0].jobId);
  }, [activeJobId, submitted]);

  // 刚攻入新的待命条目时自动展示待命视图，避免用户以为没加上。
  useEffect(() => {
    if (pending.length) setQueueView("pending");
  }, [pending.length]);

  return (
    <div className="tasks-console">
      <section className="tasks-panel tasks-panel--form">
        <div className="tasks-panel__header">
          <h2>推理参数</h2>
        </div>
        <UploadForm
          activeJobId={activeJobId}
          onSubmitted={(jobId) => {
            setActiveJobId(jobId);
            setQueueView("submitted");
            void queryClient.invalidateQueries({ queryKey: queryKeys.jobsAll });
          }}
          onCancelled={(jobId) => {
            void queryClient.invalidateQueries({ queryKey: queryKeys.job(jobId) });
            void queryClient.invalidateQueries({ queryKey: queryKeys.jobsAll });
          }}
        />
      </section>

      <section className="tasks-panel tasks-panel--history">
        <HistoryJobs onSelect={setActiveJobId} />
      </section>

      <section className="tasks-main">
        <JobQueuePanel
          view={queueView}
          onViewChange={setQueueView}
          onSelectJob={setActiveJobId}
          activeJobId={activeJobId}
        />

        <section className="tasks-panel tasks-panel--runtime">
          <RuntimeView jobId={activeJobId} />
        </section>
      </section>
    </div>
  );
}

/**
 * 作业队列：一个面板、两个视图。
 * 「待命」= 本地攒着、还可以增删改排的条目；「已提交」= 后端已接手、只能观察的作业。
 */
function JobQueuePanel({
  view,
  onViewChange,
  onSelectJob,
  activeJobId,
}: {
  view: QueueView;
  onViewChange: (view: QueueView) => void;
  onSelectJob: (jobId: string) => void;
  activeJobId?: string;
}) {
  const pending = useJobsStore((s) => s.pending);
  const submitted = useJobsStore((s) => s.submitted);
  const clearPending = useJobsStore((s) => s.clearPending);
  const clearSubmitted = useJobsStore((s) => s.clearSubmitted);
  const queryClient = useQueryClient();

  const stopWorker = useMutation({
    mutationFn: endpoints.stopWorker,
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobsAll });
      if (activeJobId) void queryClient.invalidateQueries({ queryKey: queryKeys.job(activeJobId) });
      message.success(result.message);
    },
    onError: (error) => message.error(error instanceof Error ? error.message : "停止推理 Worker 失败"),
  });

  return (
    <div className="tasks-panel tasks-panel--queue">
      <div className="tasks-panel__header tasks-panel__header--split">
        <div className="task-queue__toolbar">
          <h2>作业队列</h2>
          <Segmented<QueueView>
            size="small"
            value={view}
            onChange={onViewChange}
            options={[
              { label: `待命 ${pending.length}`, value: "pending" },
              { label: `已提交 ${submitted.length}`, value: "submitted" },
            ]}
          />
        </div>
        {view === "pending" ? (
          <Popconfirm
            title="清空待命队列"
            description={`将移除全部 ${pending.length} 条待命条目，此操作不可撤销。`}
            okText="清空"
            okButtonProps={{ danger: true }}
            cancelText="取消"
            onConfirm={clearPending}
            disabled={!pending.length}
          >
            <Button size="small" danger disabled={!pending.length}>
              清空待命
            </Button>
          </Popconfirm>
        ) : (
          <div className="task-queue__ops">
            <Button size="small" type="text" disabled={!submitted.length} onClick={clearSubmitted}>
              清空记录
            </Button>
            <Button
              danger
              size="small"
              icon={<PoweroffOutlined />}
              loading={stopWorker.isPending}
              onClick={() => {
                Modal.confirm({
                  title: "停止推理 Worker 并释放模型内存",
                  content:
                    "将取消全部排队/运行中的推理任务，并停止本机 worker。后续推理前需重新启动 worker。",
                  okText: "停止并释放内存",
                  okButtonProps: { danger: true },
                  cancelText: "取消",
                  onOk: () => stopWorker.mutate(),
                });
              }}
            >
              释放 Worker
            </Button>
          </div>
        )}
      </div>
      <div className="task-scroll-window task-scroll-window--queue">
        {view === "pending" ? (
          <PendingQueueTable />
        ) : (
          <SubmittedJobsTable onSelectJob={onSelectJob} />
        )}
      </div>
    </div>
  );
}

function PendingQueueTable() {
  const pending = useJobsStore((s) => s.pending);
  const removePending = useJobsStore((s) => s.removePending);
  const undoRemove = useJobsStore((s) => s.undoRemove);
  const movePending = useJobsStore((s) => s.movePending);
  const editPending = useJobsStore((s) => s.editPending);

  // 单条删除不拦截，改用可撤销提示；只有不可逆的批量操作才值得弹窗。
  function handleRemove(task: PendingTask) {
    removePending(task.id);
    const key = `undo-${task.id}`;
    message.open({
      key,
      type: "success",
      duration: 5,
      content: (
        <span className="task-queue__undo">
          {`已移除「${task.displayName}」`}
          <Button
            type="link"
            size="small"
            onClick={() => {
              undoRemove();
              message.destroy(key);
            }}
          >
            撤销
          </Button>
        </span>
      ),
    });
  }

  const columns: TableProps<PendingTask>["columns"] = [
    {
      title: "#",
      key: "index",
      width: 40,
      render: (_: unknown, __: PendingTask, index: number) => (
        <span className="mono">{index + 1}</span>
      ),
    },
    {
      title: "输入",
      dataIndex: "displayName",
      key: "displayName",
      ellipsis: true,
      render: (value: string, row) => (
        <Tooltip title={row.fullPath} placement="topLeft">
          <span>
            {value}
            {row.fromUpload ? <Tag className="task-queue__tag">上传</Tag> : null}
          </span>
        </Tooltip>
      ),
    },
    {
      title: "地块 ID",
      dataIndex: "tractId",
      key: "tractId",
      ellipsis: true,
      render: (value: string | undefined, row) =>
        value ? value : <span className="task-queue__fallback">{stem(row.displayName)}</span>,
    },
    {
      title: "时相",
      dataIndex: "phaseId",
      key: "phaseId",
      width: 96,
      render: (value: string | undefined) =>
        value ? (
          <span className="mono">{value}</span>
        ) : (
          <span className="task-queue__fallback">读元数据</span>
        ),
    },
    {
      title: "参数",
      key: "params",
      render: (_: unknown, row: PendingTask) => (
        <Tooltip title={paramsDetail(row)} placement="topLeft">
          <span className="task-queue__params mono">{paramsSummary(row)}</span>
        </Tooltip>
      ),
    },
    {
      title: "操作",
      key: "ops",
      width: 132,
      render: (_: unknown, row: PendingTask, index: number) => (
        <div className="task-queue__ops">
          <Tooltip title="上移">
            <Button
              type="text"
              size="small"
              icon={<ArrowUpOutlined />}
              disabled={index === 0}
              onClick={() => movePending(row.id, -1)}
            />
          </Tooltip>
          <Tooltip title="下移">
            <Button
              type="text"
              size="small"
              icon={<ArrowDownOutlined />}
              disabled={index === pending.length - 1}
              onClick={() => movePending(row.id, 1)}
            />
          </Tooltip>
          <Tooltip title={row.fromUpload ? "上传的影像无法回填表单，请删除后重新上传" : "回填到左侧表单继续编辑"}>
            <Button
              type="text"
              size="small"
              icon={<EditOutlined />}
              disabled={row.fromUpload}
              onClick={() => editPending(row.id)}
            />
          </Tooltip>
          <Tooltip title="移除">
            <Button
              type="text"
              size="small"
              danger
              icon={<CloseOutlined />}
              onClick={() => handleRemove(row)}
            />
          </Tooltip>
        </div>
      ),
    },
  ];

  return (
    <Table<PendingTask>
      rowKey="id"
      size="small"
      columns={columns}
      dataSource={pending}
      pagination={false}
      locale={PENDING_LOCALE}
    />
  );
}

function SubmittedJobsTable({ onSelectJob }: { onSelectJob: (jobId: string) => void }) {
  const submitted = useJobsStore((s) => s.submitted);

  const columns: TableProps<SubmittedJob>["columns"] = [
    {
      title: "输入",
      dataIndex: "filename",
      key: "filename",
      ellipsis: true,
      render: (v: string, r) => (
        <button className="task-link" type="button" onClick={() => onSelectJob(r.jobId)}>
          {v}
        </button>
      ),
    },
    {
      title: "条目",
      dataIndex: "itemCount",
      key: "itemCount",
      width: 72,
      render: (v: number | undefined) => <span className="mono">{v ?? 1}</span>,
    },
    {
      title: "地块 ID",
      dataIndex: "tractId",
      key: "tractId",
      ellipsis: true,
      render: (v: string | undefined) => v || "-",
    },
    {
      title: "状态",
      key: "status",
      render: (_: unknown, r: SubmittedJob) => <JobStatusCell jobId={r.jobId} />,
    },
    {
      title: "提交时间",
      dataIndex: "submittedAt",
      key: "submittedAt",
      render: (v: number) => new Date(v).toLocaleString(),
    },
  ];

  return (
    <Table<SubmittedJob>
      rowKey="jobId"
      size="small"
      columns={columns}
      dataSource={submitted}
      pagination={false}
      locale={TABLE_LOCALE}
      expandable={{
        expandedRowRender: (row) => <SubmittedJobItems jobId={row.jobId} />,
        rowExpandable: (row) => (row.itemCount ?? 1) > 1,
      }}
    />
  );
}

/** 展开行：一个批次内逐张影像的结果。 */
function SubmittedJobItems({ jobId }: { jobId: string }) {
  const { data } = useJob(jobId);
  const items = batchItems(data);
  if (!items.length) return <span className="task-queue__fallback">暂无明细，作业可能尚未开始。</span>;
  return <BatchItemList items={items} />;
}

function HistoryJobs({ onSelect }: { onSelect: (jobId: string) => void }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const phaseId = searchParams.get("phase_id")?.trim() || undefined;
  const tiffId = searchParams.get("tiff_id")?.trim() || undefined;
  const hasAssetFilter = Boolean(phaseId || tiffId);
  const taskType = hasAssetFilter ? JOB_TASK_TYPES_WITH_REVIEW : JOB_TASK_TYPES;
  const { data = [] } = useQuery({
    queryKey: queryKeys.jobs(taskType, phaseId, tiffId),
    queryFn: () => endpoints.listJobs({ taskType, phaseId, tiffId, limit: 80 }),
    refetchInterval: 5000,
  });

  const columns: TableProps<JobHistoryItem>["columns"] = [
    {
      title: "运行 ID",
      dataIndex: "run_id",
      key: "run_id",
      ellipsis: true,
      render: (v: string) => (
        <button className="task-link" type="button" onClick={() => onSelect(v)}>
          {v}
        </button>
      ),
    },
    {
      title: "类型",
      dataIndex: "task_type",
      key: "task_type",
      width: 76,
      render: (value: string) =>
        value === "review" ? "复核" : value === "infer" ? "推理" : value === "batch" ? "批量" : value,
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      render: (v: JobState) => <StatusTag status={v} />,
    },
    {
      title: "时间",
      dataIndex: "started_at",
      key: "started_at",
      render: (v: string | null | undefined) => (v ? new Date(v).toLocaleString() : "-"),
    }
  ];

  return (
    <>
      <div className="tasks-panel__header tasks-panel__header--split">
        <h2>历史作业</h2>
        {hasAssetFilter ? (
          <Button size="small" type="link" onClick={() => setSearchParams({})}>
            清除 TIFF 筛选
          </Button>
        ) : null}
      </div>
      {hasAssetFilter ? (
        <div style={{ padding: "0 12px 8px" }}>
          <Tag color="blue">时相 {phaseId ?? "全部"}</Tag>
          <Tag color="blue">TIFF {tiffId ?? "全部"}</Tag>
        </div>
      ) : null}
      <div className="task-scroll-window task-scroll-window--history">
        <Table<JobHistoryItem>
          rowKey="run_id"
          size="small"
          columns={columns}
          dataSource={data}
          pagination={false}
          locale={TABLE_LOCALE}
        />
      </div>
    </>
  );
}

function RuntimeView({ jobId }: { jobId?: string }) {
  const { data } = useJob(jobId);
  const navigate = useNavigate();
  const [cursor, setCursor] = useState(0);
  const [lines, setLines] = useState<string[]>([]);

  useEffect(() => {
    setCursor(0);
    setLines([]);
  }, [jobId]);

  useEffect(() => {
    const activeId = jobId ?? "";
    if (!activeId) return undefined;
    let cancelled = false;

    async function pull() {
      try {
        const res = await endpoints.getJobLogs(activeId, cursor);
        if (cancelled) return;
        if (res.lines.length) setLines((old) => [...old, ...res.lines].slice(-800));
        setCursor(res.cursor);
      } catch {
        /* 日志可用性不影响状态轮询。 */
      }
    }

    const terminal =
      data?.status === "succeeded" || data?.status === "failed" || data?.status === "canceled";
    void pull();
    const timer = terminal
      ? undefined
      : window.setInterval(() => {
          if (!document.hidden) {
            void pull();
          }
        }, 1500);
    return () => {
      cancelled = true;
      if (timer) window.clearInterval(timer);
    };
  }, [cursor, data?.status, jobId]);

  if (!jobId) {
    return (
      <div className="runtime-empty">
        <Empty description="暂无活动作业" />
      </div>
    );
  }

  return (
    <>
      <div className="tasks-panel__header tasks-panel__header--split">
        <div>
          <h2>运行追踪</h2>
          <span className="mono tasks-job-id">{jobId}</span>
        </div>
        <StatusTag status={data?.status ?? "queued"} />
      </div>

      <MetricsBoard status={data} />
      <LogConsole lines={lines} />
      {data?.status === "succeeded" ? (
        <div className="task-result-actions">
          <Button
            type="primary"
            icon={<ExportOutlined />}
            onClick={() => navigate("/ledger?run_id=" + encodeURIComponent(jobId))}
          >
            成果产出
          </Button>
        </div>
      ) : null}
      <BatchItems status={data} />
    </>
  );
}

function MetricsBoard({ status }: { status?: JobStatus }) {
  const metrics = status?.metrics ?? {};
  const cards = [
    ["瓦片", metricText(metrics.tiles_processed, metrics.tiles_total)],
    ["原始框", metricText(metrics.raw_count)],
    ["融合后", metricText(metrics.fused_count ?? metrics.total_trees)],
    ["耗时", durationText(status?.duration_s ?? metrics.duration_s)],
    ["成功", metricText(metrics.succeeded, metrics.total)],
    ["失败", metricText(metrics.failed)],
    ["已取消", metricText(metrics.canceled)],
  ];

  return (
    <div className="task-metrics">
      {cards.map(([label, value]) => (
        <div className="task-metric" key={label}>
          <span>{label}</span>
          <strong className="mono">{value}</strong>
        </div>
      ))}
    </div>
  );
}

function LogConsole({ lines }: { lines: string[] }) {
  return (
    <div className="task-log">
      {lines.length ? (
        lines.map((line, idx) => (
          <div className="task-log__line" key={`${idx}-${line}`}>
            {line}
          </div>
        ))
      ) : (
        <div className="task-log__empty">等待日志输出</div>
      )}
    </div>
  );
}

function BatchItems({ status }: { status?: JobStatus }) {
  const items = useMemo(() => batchItems(status), [status]);
  if (!items.length) return null;
  return (
    <div className="task-batch">
      <div className="task-batch__title">批量明细</div>
      <BatchItemList items={items} />
    </div>
  );
}

function BatchItemList({ items }: { items: BatchItemRow[] }) {
  return (
    <div className="task-batch__rows">
      {items.map((item, idx) => {
        const meta = ITEM_STATUS[item.status ?? ""] ?? { color: "default", text: item.status ?? "-" };
        return (
          <div className="task-batch__row" key={item.run_id ?? `${idx}-${item.path ?? ""}`}>
            <Tooltip title={item.error || item.path} placement="topLeft">
              <span>{item.tract_key ?? item.path ?? "-"}</span>
            </Tooltip>
            <Tag color={meta.color}>{meta.text}</Tag>
            <strong className="mono">{item.tree_count ?? 0}</strong>
          </div>
        );
      })}
    </div>
  );
}

function StatusTag({ status }: { status: JobState }) {
  const color =
    status === "succeeded"
      ? "success"
      : status === "failed"
        ? "error"
        : status === "canceled"
          ? "default"
          : "processing";
  return <Tag color={color}>{STATUS_TEXT[status]}</Tag>;
}

function batchItems(status?: JobStatus): BatchItemRow[] {
  const raw = status?.metrics?.items;
  return Array.isArray(raw) ? (raw as BatchItemRow[]) : [];
}

/** 待命项参数摘要：切片 / 覆盖率 / 导出格式（+ 辅助数据标记）。 */
function paramsSummary(task: PendingTask) {
  const parts = [
    task.tileSize ? String(task.tileSize) : "自适应",
    typeof task.overlapRate === "number" ? `${Math.round(task.overlapRate * 100)}%` : "自适应",
    task.exportFmt ?? "shp",
  ];
  const aux = [task.dsm ? "DSM" : "", task.dem ? "DEM" : "", task.las ? "LAS" : ""].filter(Boolean);
  return aux.length ? `${parts.join(" / ")} +${aux.join(",")}` : parts.join(" / ");
}

function paramsDetail(task: PendingTask) {
  const rows = [
    `切片尺寸：${task.tileSize ?? "默认自适应"}`,
    `覆盖率：${typeof task.overlapRate === "number" ? `${Math.round(task.overlapRate * 100)}%` : "默认自适应"}`,
    `导出格式：${task.exportFmt ?? "shp"}`,
  ];
  if (task.dsm) rows.push(`DSM：${task.dsm}`);
  if (task.dem) rows.push(`DEM：${task.dem}`);
  if (task.las) rows.push(`LAS：${task.las}`);
  return <div className="task-queue__tooltip">{rows.map((row) => <div key={row}>{row}</div>)}</div>;
}

function stem(name: string) {
  const idx = name.lastIndexOf(".");
  return idx > 0 ? name.slice(0, idx) : name;
}

function metricText(value: unknown, total?: unknown) {
  const primary = typeof value === "number" ? value : "-";
  if (typeof total === "number") return `${primary}/${total}`;
  return String(primary);
}

function durationText(value: unknown) {
  return typeof value === "number" ? `${value.toFixed(1)}s` : "-";
}
