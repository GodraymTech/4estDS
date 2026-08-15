import { useEffect, useState } from "react";
import { App, Button, Empty, Popconfirm, Table, Tag, Tooltip } from "antd";
import type { TableProps } from "antd";
import {
    ClearOutlined,
    FolderOpenOutlined,
    PoweroffOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { endpoints, queryKeys, type JobHistoryItem, type JobState, type JobStatus } from "../../shared/api";
import { useJob } from "../../entities/run";
import { UploadForm } from "./UploadForm";
import { JobStatusCell } from "./JobStatusCell";
import { useJobsStore, type SubmittedJob } from "./jobsStore";
import "./TasksCenter.css";

// 历史列表包含单图推理(infer)、多图批量(batch)与复核(review)顶层作业。
const JOB_TASK_TYPES = "infer,batch,review";

const TABLE_LOCALE = { emptyText: <Empty description="暂无作业" /> };

const STATUS_TEXT: Record<JobState, string> = {
    queued: "排队中",
    running: "推理中",
    succeeded: "已完成",
    failed: "失败",
    canceled: "已取消",
};

export function TasksCenter() {
    const submitted = useJobsStore((s) => s.submitted);
    const [activeJobId, setActiveJobId] = useState<string | undefined>(submitted[0]?.jobId);
    const queryClient = useQueryClient();

    useEffect(() => {
        if (!activeJobId && submitted[0]?.jobId) setActiveJobId(submitted[0].jobId);
    }, [activeJobId, submitted]);

    return (
        <div className="tasks-console">
            <div className="tasks-sidebar">
                <section className="tasks-panel tasks-panel--form">
                    <div className="tasks-panel__header">
                        <h2>推理参数</h2>
                    </div>
                    <UploadForm
                        activeJobId={activeJobId}
                        onSubmitted={(jobId) => {
                            setActiveJobId(jobId);
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
            </div>

            <section className="tasks-main">
                <JobQueuePanel
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

/** 作业队列面板：展示当前会话提交的异步推理作业。 */
function JobQueuePanel({
    onSelectJob,
    activeJobId,
}: {
    onSelectJob: (jobId: string) => void;
    activeJobId?: string;
}) {
    const submitted = useJobsStore((s) => s.submitted);
    const clearSubmitted = useJobsStore((s) => s.clearSubmitted);
    const queryClient = useQueryClient();
    const { modal, message } = App.useApp();

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
                <h2>作业队列</h2>
                <div className="task-queue__ops">
                    <Popconfirm
                        title="清空作业记录"
                        description={`将清空本地记录的 ${submitted.length} 条已提交条目，此操作不可撤销。`}
                        okText="清空"
                        okButtonProps={{ danger: true }}
                        cancelText="取消"
                        onConfirm={clearSubmitted}
                        disabled={!submitted.length}
                    >
                        <Button
                            size="small"
                            icon={<ClearOutlined />}
                            disabled={!submitted.length}
                            className="task-pill-btn task-pill-btn--clear"
                        >
                            清空记录
                        </Button>
                    </Popconfirm>
                    <Button
                        danger
                        size="small"
                        icon={<PoweroffOutlined />}
                        loading={stopWorker.isPending}
                        className="task-pill-btn task-pill-btn--worker"
                        onClick={() => {
                            modal.confirm({
                                title: "停止推理 Worker 并释放模型内存",
                                content: "取消全部排队/运行中的推理任务，停止本机 worker。",
                                okText: "确认",
                                okButtonProps: { danger: true },
                                cancelText: "取消",
                                onOk: () => stopWorker.mutate(),
                            });
                        }}
                    >
                        释放 Worker
                    </Button>
                </div>
            </div>
            <div className="task-scroll-window task-scroll-window--queue">
                <SubmittedJobsTable onSelectJob={onSelectJob} activeJobId={activeJobId} />
            </div>
        </div>
    );
}

function SubmittedJobsTable({
    onSelectJob,
    activeJobId,
}: {
    onSelectJob: (jobId: string) => void;
    activeJobId?: string;
}) {
    const submitted = useJobsStore((s) => s.submitted);

    const columns: TableProps<SubmittedJob>["columns"] = [
        {
            title: "运行 ID",
            dataIndex: "jobId",
            key: "jobId",
            width: 100,
            render: (v: string) => (
                <button
                    className={`task-link mono ${v === activeJobId ? "is-selected" : ""}`}
                    type="button"
                    onClick={() => onSelectJob(v)}
                    title={v}
                >
                    {v.length > 8 ? v.slice(0, 8) : v}
                </button>
            ),
        },
        {
            title: "输入影像",
            dataIndex: "filename",
            key: "filename",
            ellipsis: true,
            render: (v: string, r) => (
                <Tooltip title={r.fullPath || v} placement="topLeft">
                    <button className="task-link" type="button" onClick={() => onSelectJob(r.jobId)}>
                        {v}
                    </button>
                </Tooltip>
            ),
        },
        {
            title: "地块 ID",
            dataIndex: "tractId",
            key: "tractId",
            ellipsis: true,
            width: 90,
            render: (v: string | undefined, r) => v || stem(r.filename) || "-",
        },
        {
            title: "时相 ID",
            dataIndex: "phaseId",
            key: "phaseId",
            width: 130,
            render: (v: string | undefined) => <span className="mono">{v || "-"}</span>,
        },
        {
            title: "切片尺寸",
            dataIndex: "tileSize",
            key: "tileSize",
            width: 86,
            render: (v: number | null | undefined) => <span className="mono">{v ? `${v}` : "自适应"}</span>,
        },
        {
            title: "重叠率",
            dataIndex: "overlapPercent",
            key: "overlapPercent",
            width: 76,
            render: (v: number | null | undefined) => (
                <span className="mono">{typeof v === "number" ? `${v}%` : "自适应"}</span>
            ),
        },
        {
            title: "状态",
            key: "status",
            width: 160,
            render: (_: unknown, r: SubmittedJob) => <JobStatusCell jobId={r.jobId} />,
        },
        {
            title: "提交时间",
            dataIndex: "submittedAt",
            key: "submittedAt",
            width: 180,
            render: (v: number) => <span className="mono">{formatFullDateTime(v)}</span>,
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
        />
    );
}

function HistoryJobs({ onSelect }: { onSelect: (jobId: string) => void }) {
    const { data = [] } = useQuery({
        queryKey: queryKeys.jobs(JOB_TASK_TYPES),
        queryFn: () => endpoints.listJobs({ taskType: JOB_TASK_TYPES, limit: 80 }),
        refetchInterval: 5000,
    });

    const columns: TableProps<JobHistoryItem>["columns"] = [
        {
            title: "运行 ID",
            dataIndex: "run_id",
            key: "run_id",
            ellipsis: true,
            render: (v: string) => (
                <button className="task-link mono" type="button" onClick={() => onSelect(v)}>
                    {v.length > 10 ? v.slice(0, 10) : v}
                </button>
            ),
        },
        {
            title: "类型",
            dataIndex: "task_type",
            key: "task_type",
            width: 64,
            render: (value: string) =>
                value === "review" ? "复核" : value === "infer" ? "推理" : value === "batch" ? "批量" : value,
        },
        {
            title: "状态",
            dataIndex: "status",
            key: "status",
            width: 76,
            render: (v: JobState) => <StatusTag status={v} />,
        },
        {
            title: "时间",
            dataIndex: "started_at",
            key: "started_at",
            width: 116,
            render: (v: string | null | undefined) => <span className="mono">{formatShortDateTime(v)}</span>,
        },
    ];

    return (
        <>
            <div className="tasks-panel__header">
                <h2>历史作业</h2>
            </div>
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

    return (
        <>
            <div className="tasks-panel__header tasks-panel__header--split">
                <div className="task-runtime__title">
                    <h2>运行详情</h2>
                    <span className="mono">{jobId || "未选择"}</span>
                    {data?.status ? <StatusTag status={data.status} /> : null}
                </div>
                {jobId && data?.status === "succeeded" ? (
                    <Button
                        size="small"
                        type="primary"
                        onClick={() => navigate(`/review?run_id=${encodeURIComponent(jobId)}`)}
                    >
                        去复核
                    </Button>
                ) : null}
            </div>

            <div className="task-runtime__grid">
                <div className="task-runtime__primary">
                    <RuntimeMetrics status={data} jobId={jobId} />
                    <RuntimeLogs jobId={jobId} status={data?.status} />
                    {jobId && data?.status === "succeeded" ? (
                        <div className="task-result-actions" style={{ marginTop: 12, display: "flex", justifyContent: "flex-end" }}>
                            <Button
                                type="primary"
                                icon={<FolderOpenOutlined />}
                                onClick={() => navigate(`/ledger?run_id=${encodeURIComponent(jobId)}`)}
                            >
                                查看推理成果
                            </Button>
                        </div>
                    ) : null}
                </div>
            </div>
        </>
    );
}

function RuntimeLogs({ jobId, status }: { jobId?: string; status?: JobState }) {
    const [cursor, setCursor] = useState(0);
    const [lines, setLines] = useState<string[]>([]);
    const isActive = status === "running" || status === "queued";

    // 切换作业时重置日志缓冲区。
    useEffect(() => {
        setCursor(0);
        setLines([]);
    }, [jobId]);

    const { data } = useQuery({
        queryKey: queryKeys.jobLogs(jobId || "", cursor),
        queryFn: () => endpoints.getJobLogs(jobId!, cursor),
        enabled: Boolean(jobId),
        refetchInterval: isActive ? 1000 : false,
    });

    useEffect(() => {
        if (!data) return;
        if (data.lines.length) {
            setLines((prev) => [...prev, ...data.lines]);
        }
        setCursor(data.cursor);
    }, [data]);

    return (
        <div className="task-log" role="region" aria-label="作业日志输出" tabIndex={0}>
            {lines.length ? (
                lines.map((line, idx) => (
                    <div className="task-log__line" key={idx}>
                        {line}
                    </div>
                ))
            ) : (
                <div className="task-log__empty">{jobId ? "等待日志输出..." : "选择作业以查看日志"}</div>
            )}
        </div>
    );
}

/** 运行详情指标区：两行四列栅格排布。 */
function RuntimeMetrics({ status, jobId }: { status?: JobStatus; jobId?: string }) {
    const submitted = useJobsStore((s) => s.submitted);
    const currentJob = submitted.find((j) => j.jobId === jobId);
    const m = status?.metrics || {};

    // 像素尺寸
    const pixelSize =
        m.image_width && m.image_height
            ? `${m.image_width}×${m.image_height}`
            : "-";

    // 切片尺寸：原始大小 → 推理时统一缩放大小 (如 2048 → 640)
    const rawTile =
        typeof m.tile_size === "number"
            ? m.tile_size
            : currentJob?.tileSize ?? null;
    const modelInput =
        typeof m.model_input === "number"
            ? m.model_input
            : null;

    const tileSize =
        rawTile && modelInput
            ? `${rawTile} → ${modelInput}`
            : rawTile
                ? `${rawTile}`
                : "自适应";

    // 重叠率
    const overlapRate =
        typeof m.overlap_rate === "number"
            ? `${Math.round(m.overlap_rate * 100)}%`
            : typeof currentJob?.overlapPercent === "number"
                ? `${currentJob.overlapPercent}%`
                : "自适应";

    // 切片数：已处理 / 已跳过 / 总数
    const processed = typeof m.tiles_processed === "number" ? m.tiles_processed : null;
    const total = typeof m.tiles_total === "number" ? m.tiles_total : null;
    const skipped =
        typeof m.tiles_skipped_empty === "number"
            ? m.tiles_skipped_empty
            : processed !== null && total !== null
                ? Math.max(0, total - processed)
                : null;

    const tilesCount =
        processed !== null && total !== null
            ? `${processed}/${skipped ?? 0}/${total}`
            : "-";

    // 原检测数
    const rawCount = metricText(m.raw_count);

    // 去重后
    const fusedCount = metricText(m.fused_count ?? m.total_trees);

    // 执行耗时
    const duration = durationText(status?.duration_s ?? m.duration_s);

    return (
        <div className="task-metrics">
            {/* 第一行：影像与切片规格 */}
            <div className="task-metric">
                <span>像素尺寸(px)</span>
                <strong className="mono">{pixelSize}</strong>
            </div>
            <div className="task-metric">
                <Tooltip title="原始大小 → 推理时统一缩放大小" placement="top">
                    <span>切片尺寸(px)</span>
                </Tooltip>
                <strong className="mono">{tileSize}</strong>
            </div>
            <div className="task-metric">
                <span>重叠率</span>
                <strong className="mono">{overlapRate}</strong>
            </div>
            <div className="task-metric">
                <span>切片数 (已推理 / 已跳过 / 总数)</span>
                <strong className="mono">{tilesCount}</strong>
            </div>

            {/* 第二行：单木检测与执行结果 */}
            <div className="task-metric">
                <span>原检测株数</span>
                <strong className="mono">{rawCount}</strong>
            </div>
            <div className="task-metric">
                <span>去重后株数</span>
                <strong className="mono">{fusedCount}</strong>
            </div>
            <div className="task-metric">
                <span>执行耗时</span>
                <strong className="mono">{duration}</strong>
            </div>
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

function stem(name: string) {
    const idx = name.lastIndexOf(".");
    return idx > 0 ? name.slice(0, idx) : name;
}

function metricText(value: unknown, total?: unknown) {
    if (typeof value === "number") {
        if (typeof total === "number") return `${value}/${total}`;
        return value.toLocaleString();
    }
    return "-";
}

function durationText(value: unknown) {
    return typeof value === "number" ? `${value.toFixed(1)}s` : "-";
}

function formatFullDateTime(val: number | string | null | undefined): string {
    if (!val) return "-";
    const d = new Date(val);
    if (isNaN(d.getTime())) return "-";
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    const hh = String(d.getHours()).padStart(2, "0");
    const min = String(d.getMinutes()).padStart(2, "0");
    const ss = String(d.getSeconds()).padStart(2, "0");
    return `${yyyy}/${mm}/${dd} ${hh}:${min}:${ss}`;
}

function formatShortDateTime(val: number | string | null | undefined): string {
    if (!val) return "-";
    const d = new Date(val);
    if (isNaN(d.getTime())) return "-";
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    const hh = String(d.getHours()).padStart(2, "0");
    const min = String(d.getMinutes()).padStart(2, "0");
    return `${mm}/${dd} ${hh}:${min}`;
}
