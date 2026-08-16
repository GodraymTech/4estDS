import { useEffect, useState } from "react";
import { App, Button, Progress, Tag } from "antd";
import { CheckOutlined, CloseOutlined, ExpandOutlined, WarningOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReviewAttempt, ReviewItem, ReviewMergeMode } from "../../shared/api";
import { endpoints, queryKeys } from "../../shared/api";
import { useReviewWorkbenchStore } from "./store";

export function AttemptPanel({
    sessionId,
    revision,
    attempts,
    mergeMode,
    onChanged,
    onPreview,
    onApplied,
}: {
    sessionId: string;
    revision: number;
    attempts: ReviewAttempt[];
    mergeMode: ReviewMergeMode;
    onChanged: (attempt: ReviewAttempt) => void;
    onPreview: (items: ReviewItem[]) => void;
    onApplied: (revision: number, items: ReviewItem[]) => void;
}) {
    const { modal, message } = App.useApp();
    const client = useQueryClient();
    const [selectedId, setSelectedId] = useState<string>();
    const [dismissedId, setDismissedId] = useState<string | null>(null);
    const [sessionActiveAttemptId, setSessionActiveAttemptId] = useState<string | null>(null);

    // 监听 attempts 变化：仅当有正在进行的任务或本会话中产生的新任务时才激活浮窗
    useEffect(() => {
        const latestAttempt = attempts[attempts.length - 1];
        const latestId = latestAttempt?.attempt_id;
        if (!latestId) return;

        // 若最新任务仍在进行中（排队或识别中），主动唤起
        if (latestAttempt.status === "queued" || latestAttempt.status === "running") {
            setSelectedId(latestId);
            setSessionActiveAttemptId(latestId);
            setDismissedId(null);
            return;
        }

        // 若是本会话中新创建的任务演进到完成态，保持展示
        if (sessionActiveAttemptId === latestId && dismissedId !== latestId) {
            setSelectedId(latestId);
            return;
        }

        // 否则（从外部重新进入会话的历史已完成任务）：默认不弹窗、不污染画布候选
        setSelectedId(latestId);
        setDismissedId(latestId);
    }, [attempts.length, attempts[attempts.length - 1]?.attempt_id, attempts[attempts.length - 1]?.status]);

    const query = useQuery({
        queryKey: ["review-attempt", sessionId, selectedId],
        queryFn: () => endpoints.getReviewAttempt(sessionId, selectedId as string),
        enabled: Boolean(selectedId && dismissedId !== selectedId),
        refetchInterval: (state) => (["queued", "running"].includes(state.state.data?.status ?? "") ? 1000 : false),
    });

    const current = query.data ?? attempts.find((item) => item.attempt_id === selectedId);

    useEffect(() => {
        if (dismissedId === selectedId) {
            onPreview([]);
            return;
        }
        if (!query.data) return;
        onChanged(query.data);
        onPreview(query.data.status === "succeeded" ? query.data.candidates : []);
        if (query.data.status === "succeeded") {
            const model = query.data.model_name || "dinov";
            const count = query.data.candidate_count ?? query.data.candidates?.length ?? 0;
            const elapsed = query.data.elapsed_seconds != null ? `${query.data.elapsed_seconds}s` : "-";
            console.log(
                `%c[Review AI]%c 引擎: %c${model}%c | 检出候选: %c${count} 个%c | 耗时: %c${elapsed}`,
                "color: #3b82f6; font-weight: bold",
                "color: inherit",
                "color: #10b981; font-weight: bold",
                "color: inherit",
                "color: #f59e0b; font-weight: bold",
                "color: inherit",
                "color: #8b5cf6"
            );
        }
    }, [query.data?.status, query.data?.progress, query.data?.candidate_count, dismissedId, selectedId]);

    const storeRevision = useReviewWorkbenchStore((state) => state.revision);

    const cancel = useMutation({
        mutationFn: () => endpoints.cancelReviewAttempt(sessionId, selectedId as string),
        onSuccess: (attempt) => {
            onChanged(attempt);
            onPreview([]);
        },
    });

    const expand = useMutation({
        mutationFn: () => endpoints.expandReviewAttempt(sessionId, selectedId as string, storeRevision ?? revision),
        onSuccess: (attempt) => {
            onChanged(attempt);
            setSelectedId(attempt.attempt_id);
            onPreview([]);
        },
    });

    const candidateThreshold = useReviewWorkbenchStore((state) => state.candidateThreshold);

    const apply = useMutation({
        mutationFn: () => endpoints.applyReviewAttempt(sessionId, selectedId as string, storeRevision ?? revision, mergeMode, candidateThreshold),
        onSuccess: (patch) => {
            onApplied(patch.revision, patch.items);
            onPreview([]);
            void client.invalidateQueries({ queryKey: queryKeys.reviewWorkspace(sessionId) });
            message.success(mergeMode === "append" ? "新候选已追加到工作集" : "工作集已由本轮候选替换");
        },
        onError: (error) => message.error(error instanceof Error ? error.message : "应用候选失败"),
    });

    const activeTool = useReviewWorkbenchStore((state) => state.activeTool);
    const isAiTool = activeTool === "ai_text" || activeTool === "ai_visual";

    if (!isAiTool || !attempts.length || !current || dismissedId === selectedId) return null;

    const allCount = current.candidates?.length ?? current.candidate_count ?? 0;
    const filteredCount = current.candidates?.length
        ? current.candidates.filter((c) => c.confidence == null || c.confidence >= candidateThreshold).length
        : current.candidate_count ?? 0;

    return (
        <section className="review-attempt-panel" aria-label="AI 识别结果">
            {/* 顶部精简标题行与关闭按钮 */}
            <div className="review-attempt-panel__header">
                <div className="review-attempt-title-area">
                    <span className="review-attempt-title">识别结果</span>
                    <Tag color={statusColor(current.status)} bordered={false} style={{ margin: 0 }}>
                        {statusLabel(current.status, current.queue_ahead_count)}
                    </Tag>
                </div>
                <button
                    type="button"
                    className="review-attempt-close-btn"
                    title="关闭该浮窗"
                    onClick={() => setDismissedId(selectedId ?? null)}
                >
                    <CloseOutlined />
                </button>
            </div>

            <Progress
                percent={current.progress}
                status={
                    current.status === "failed" || current.status === "canceled"
                        ? "exception"
                        : ["succeeded", "applied"].includes(current.status)
                            ? "success"
                            : "active"
                }
                size="small"
                strokeWidth={3}
            />

            {/* 极简双列元数据条 */}
            <div className="review-attempt-stats-grid">
                <div className="stat-item">
                    <span className="stat-k">范围</span>
                    <span className="stat-v">{current.scope.type === "full" ? "全图" : `${Math.round(current.scope.side_px)}px`}</span>
                </div>
                <div className="stat-item">
                    <span className="stat-k">耗时</span>
                    <span className="stat-v">{current.elapsed_seconds == null ? "—" : `${current.elapsed_seconds.toFixed(1)}s`}</span>
                </div>
                <div className="stat-item">
                    <span className="stat-k">切片</span>
                    <span className="stat-v">{current.completed_windows}/{current.total_windows}</span>
                </div>
                <div className="stat-item">
                    <span className="stat-k">候选</span>
                    <span className="stat-v">
                        {filteredCount === allCount ? `${filteredCount}` : `${filteredCount}/${allCount}`}
                    </span>
                </div>
            </div>

            {/* 深色毛玻璃错误卡片 */}
            {current.error ? (
                <div className="review-attempt-error-box">
                    <div className="error-box-top">
                        <span className="error-box-headline">
                            <WarningOutlined />
                            <span>探测失败</span>
                        </span>
                        <button
                            type="button"
                            className="error-box-btn"
                            onClick={() => modal.error({
                                title: "AI 识别异常详情",
                                content: (
                                    <pre style={{ maxHeight: 300, overflow: "auto", fontSize: 11, background: "rgba(0,0,0,0.05)", padding: 8, borderRadius: 4 }}>
                                        {current.error}
                                    </pre>
                                ),
                            })}
                        >
                            详情
                        </button>
                    </div>
                    <div className="error-box-content">{current.error}</div>
                </div>
            ) : null}

            {/* 操作按钮区 */}
            <div className="review-attempt-panel__actions">
                {["queued", "running"].includes(current.status) ? (
                    <Button
                        type="primary"
                        danger
                        size="small"
                        icon={<CloseOutlined />}
                        loading={cancel.isPending}
                        onClick={() => cancel.mutate()}
                        style={{ width: "45%", margin: "4px auto 0", alignSelf: "center", fontSize: 11, fontWeight: 700, height: 24 }}
                    >
                        中止
                    </Button>
                ) : null}

                {current.status === "succeeded" ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 5, width: "80%", margin: "6px auto 0", alignSelf: "center" }}>
                        <Button
                            type="primary"
                            size="small"
                            block
                            icon={<CheckOutlined />}
                            loading={apply.isPending}
                            onClick={() => apply.mutate()}
                            style={{ fontSize: 11, fontWeight: 700, height: 24, padding: "0 6px" }}
                        >
                            {mergeMode === "append" ? "追加至工作集" : "替换当前工作集"}
                        </Button>
                        {current.scope.type === "region" ? (
                            <Button
                                size="small"
                                block
                                icon={<ExpandOutlined />}
                                loading={expand.isPending}
                                onClick={() => expand.mutate()}
                                style={{ fontSize: 11, fontWeight: 700, height: 24, padding: "0 6px" }}
                            >
                                扩散至全图
                            </Button>
                        ) : null}
                    </div>
                ) : null}
            </div>
        </section>
    );
}

function statusColor(status: ReviewAttempt["status"]): string {
    if (status === "succeeded" || status === "applied") return "success";
    if (status === "failed" || status === "canceled") return "error";
    return "processing";
}

function statusLabel(status: ReviewAttempt["status"], queueAheadCount?: number): string {
    if (status === "queued") {
        return queueAheadCount && queueAheadCount > 0 ? `排队中 (还需等待 ${queueAheadCount} 个作业)` : "排队中";
    }
    return ({ running: "识别中", succeeded: "待确认", failed: "已失败", canceled: "已取消", applied: "已采纳" })[status] ?? status;
}
