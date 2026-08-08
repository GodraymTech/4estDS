import { useEffect, useState } from "react";
import { Button, Progress, Select, Space, Tag, message } from "antd";
import { CheckOutlined, CloseCircleOutlined, CloseOutlined, ExpandOutlined } from "@ant-design/icons";
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

  const apply = useMutation({
    mutationFn: () => endpoints.applyReviewAttempt(sessionId, selectedId as string, storeRevision ?? revision, mergeMode),
    onSuccess: (patch) => {
      onApplied(patch.revision, patch.items);
      onPreview([]);
      void client.invalidateQueries({ queryKey: queryKeys.reviewWorkspace(sessionId) });
      message.success(mergeMode === "append" ? "新候选已追加到工作集" : "工作集已由本轮候选替换");
    },
    onError: (error) => message.error(error instanceof Error ? error.message : "应用候选失败"),
  });

  if (!attempts.length || !current || dismissedId === selectedId) return null;

  return (
    <section className="review-attempt-panel" aria-label="AI 识别结果">
      {/* 顶部标题行：保证识别结果永不竖排换行 */}
      <div className="review-attempt-panel__header">
        <div className="review-attempt-title-area">
          <span className="review-attempt-title">识别结果</span>
          <Tag color={statusColor(current.status)} bordered={false} style={{ margin: 0 }}>
            {statusLabel(current.status)}
          </Tag>
          {current.candidate_count != null ? (
            <Tag color="cyan" bordered={false} style={{ margin: 0 }}>
              候选 {current.candidate_count}
            </Tag>
          ) : null}
        </div>

        <div className="review-attempt-tools">
          <Select
            size="small"
            value={selectedId}
            options={attempts.map((item, index) => ({
              value: item.attempt_id,
              label: `#${index + 1} · ${item.prompt_type === "text" ? "文本" : "视觉"} · ${statusLabel(item.status)}`,
            }))}
            onChange={(val) => {
              setSelectedId(val);
              setDismissedId(null);
            }}
            className="review-attempt-select"
          />
          <button
            type="button"
            className="review-attempt-close-btn"
            title="关闭该浮窗"
            onClick={() => setDismissedId(selectedId ?? null)}
          >
            <CloseOutlined />
          </button>
        </div>
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

      {/* 极简等宽单行元数据统计条，彻底消除换行折叠 */}
      <div className="review-attempt-stats-grid">
        <div className="stat-item">
          <span className="stat-k">范围:</span>
          <span className="stat-v">{current.scope.type === "full" ? "全图" : `${Math.round(current.scope.side_px)} px`}</span>
        </div>
        <div className="stat-item">
          <span className="stat-k">切片:</span>
          <span className="stat-v">{current.completed_windows}/{current.total_windows}</span>
        </div>
        <div className="stat-item">
          <span className="stat-k">跳过:</span>
          <span className="stat-v">{current.skipped_windows ?? 0}</span>
        </div>
        <div className="stat-item">
          <span className="stat-k">耗时:</span>
          <span className="stat-v">{current.elapsed_seconds == null ? "—" : `${current.elapsed_seconds.toFixed(1)} s`}</span>
        </div>
      </div>

      {/* 优雅深色毛玻璃错误卡片 */}
      {current.error ? (
        <div className="review-attempt-error-box">
          <div className="error-box-top">
            <div className="error-box-headline">
              <CloseCircleOutlined style={{ color: "#ef4444" }} />
              <span>未能生成候选</span>
            </div>
            <button
              type="button"
              className="error-box-btn"
              onClick={() => setDismissedId(selectedId ?? null)}
            >
              知道了
            </button>
          </div>
          <div className="error-box-content">{current.error}</div>
        </div>
      ) : null}

      {/* 操作按钮区 */}
      <div className="review-attempt-panel__actions">
        {["queued", "running"].includes(current.status) ? (
          <Button danger size="small" icon={<CloseOutlined />} loading={cancel.isPending} onClick={() => cancel.mutate()}>
            中止识别
          </Button>
        ) : null}

        {current.status === "succeeded" ? (
          <Space size={6}>
            <Button
              type="primary"
              size="small"
              icon={<CheckOutlined />}
              loading={apply.isPending}
              onClick={() => apply.mutate()}
            >
              {mergeMode === "append" ? "确认追加到工作集" : "确认替换当前工作集"}
            </Button>
            {current.scope.type === "region" ? (
              <Button size="small" icon={<ExpandOutlined />} loading={expand.isPending} onClick={() => expand.mutate()}>
                扩散至全图
              </Button>
            ) : null}
          </Space>
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

function statusLabel(status: ReviewAttempt["status"]): string {
  return ({ queued: "排队中", running: "识别中", succeeded: "待确认", failed: "已失败", canceled: "已取消", applied: "已采纳" })[status];
}
