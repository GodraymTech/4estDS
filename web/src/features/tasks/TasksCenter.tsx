import { useEffect, useMemo, useState } from "react";
import { Button, Empty, Table, Tag } from "antd";
import type { TableProps } from "antd";
import { ExportOutlined } from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { endpoints, queryKeys, type JobHistoryItem, type JobState, type JobStatus } from "../../shared/api";
import { useJob } from "../../entities/run";
import { UploadForm } from "./UploadForm";
import { JobStatusCell } from "./JobStatusCell";
import { useJobsStore, type SubmittedJob } from "./jobsStore";
import "./TasksCenter.css";

const TABLE_LOCALE = { emptyText: <Empty description="暂无作业" /> };

const STATUS_TEXT: Record<JobState, string> = {
  queued: "排队中",
  running: "推理中",
  succeeded: "已完成",
  failed: "失败",
  canceled: "已取消",
};

export function TasksCenter() {
  const jobs = useJobsStore((s) => s.jobs);
  const [activeJobId, setActiveJobId] = useState<string | undefined>(jobs[0]?.jobId);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!activeJobId && jobs[0]?.jobId) setActiveJobId(jobs[0].jobId);
  }, [activeJobId, jobs]);

  const columns: TableProps<SubmittedJob>["columns"] = [
    {
      title: "输入",
      dataIndex: "filename",
      key: "filename",
      ellipsis: true,
      render: (v: string, r) => (
        <button className="task-link" type="button" onClick={() => setActiveJobId(r.jobId)}>
          {v}
        </button>
      ),
    },
    {
      title: "类型",
      dataIndex: "sourceKind",
      key: "sourceKind",
      render: (v: SubmittedJob["sourceKind"]) => {
        if (v === "directory") return <Tag color="blue">批量</Tag>;
        if (v === "upload") return <Tag>上传</Tag>;
        return <Tag color="green">单图</Tag>;
      },
    },
    {
      title: "地块 ID",
      dataIndex: "tractId",
      key: "tractId",
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
    <div className="tasks-console">
      <section className="tasks-panel tasks-panel--form">
        <div className="tasks-panel__header">
          <h2>推理参数</h2>
        </div>
        <UploadForm
          activeJobId={activeJobId}
          onSubmitted={(jobId) => {
            setActiveJobId(jobId);
            void queryClient.invalidateQueries({ queryKey: queryKeys.jobs("infer") });
          }}
          onCancelled={(jobId) => {
            void queryClient.invalidateQueries({ queryKey: queryKeys.job(jobId) });
            void queryClient.invalidateQueries({ queryKey: queryKeys.jobs("infer") });
          }}
        />
      </section>

      <section className="tasks-panel tasks-panel--history">
        <div className="tasks-panel__header">
          <h2>历史作业</h2>
        </div>
        <HistoryJobs onSelect={setActiveJobId} />
      </section>

      <section className="tasks-main">
        <div className="tasks-panel tasks-panel--queue">
          <div className="tasks-panel__header">
            <h2>作业队列</h2>
          </div>
          <div className="task-scroll-window task-scroll-window--queue">
            <Table<SubmittedJob>
              rowKey="jobId"
              size="small"
              columns={columns}
              dataSource={jobs}
              pagination={false}
              locale={TABLE_LOCALE}
            />
          </div>
        </div>

        <section className="tasks-panel tasks-panel--runtime">
          <RuntimeView jobId={activeJobId} />
        </section>
      </section>
    </div>
  );
}

function HistoryJobs({ onSelect }: { onSelect: (jobId: string) => void }) {
  const { data = [] } = useQuery({
    queryKey: queryKeys.jobs("infer"),
    queryFn: () => endpoints.listJobs("infer", 80),
    refetchInterval: 5000,
  });

  const columns: TableProps<JobHistoryItem>["columns"] = [
    {
      title: "作业",
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
    },
  ];

  return (
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

    const terminal = data?.status === "succeeded" || data?.status === "failed";
    void pull();
    const timer = terminal ? undefined : window.setInterval(() => void pull(), 1200);
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
    ["批量成功", metricText(metrics.succeeded, metrics.total)],
    ["批量失败", metricText(metrics.failed)],
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
  const items = useMemo(() => {
    const raw = status?.metrics?.items;
    return Array.isArray(raw) ? raw : [];
  }, [status?.metrics?.items]);

  if (!items.length) return null;
  return (
    <div className="task-batch">
      <div className="task-batch__title">批量明细</div>
      <div className="task-batch__rows">
        {items.map((item, idx) => {
          const row = item as Record<string, unknown>;
          return (
            <div className="task-batch__row" key={String(row.run_id ?? idx)}>
              <span>{String(row.tract_key ?? row.path ?? "-")}</span>
              <Tag color={row.status === "succeeded" ? "success" : "error"}>
                {row.status === "succeeded" ? "完成" : "失败"}
              </Tag>
              <strong className="mono">{String(row.tree_count ?? 0)}</strong>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function StatusTag({ status }: { status: JobState }) {
  const color = status === "succeeded" ? "success" : status === "failed" ? "error" : "processing";
  return <Tag color={color}>{STATUS_TEXT[status]}</Tag>;
}

function metricText(value: unknown, total?: unknown) {
  const primary = typeof value === "number" ? value : "-";
  if (typeof total === "number") return `${primary}/${total}`;
  return String(primary);
}

function durationText(value: unknown) {
  return typeof value === "number" ? `${value.toFixed(1)}s` : "-";
}
