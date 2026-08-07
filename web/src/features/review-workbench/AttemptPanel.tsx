import { useEffect, useState } from "react";
import { Alert, Button, Descriptions, Progress, Select, Space, Tag, Typography, message } from "antd";
import { CheckOutlined, CloseOutlined, ExpandOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReviewAttempt, ReviewItem, ReviewMergeMode } from "../../shared/api";
import { endpoints, queryKeys } from "../../shared/api";

export function AttemptPanel({ sessionId, revision, attempts, mergeMode, onChanged, onPreview, onApplied }: {
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
  useEffect(() => {
    const latest = attempts[attempts.length - 1]?.attempt_id;
    if (latest && !attempts.some((item) => item.attempt_id === selectedId)) setSelectedId(latest);
    else if (latest && selectedId !== latest) setSelectedId(latest);
  }, [attempts.length, attempts[attempts.length - 1]?.attempt_id]);

  const query = useQuery({
    queryKey: ["review-attempt", sessionId, selectedId],
    queryFn: () => endpoints.getReviewAttempt(sessionId, selectedId as string),
    enabled: Boolean(selectedId),
    refetchInterval: (state) => ["queued", "running"].includes(state.state.data?.status ?? "") ? 1000 : false,
  });
  const current = query.data ?? attempts.find((item) => item.attempt_id === selectedId);
  useEffect(() => {
    if (!query.data) return;
    onChanged(query.data);
    onPreview(query.data.status === "succeeded" ? query.data.candidates : []);
  }, [query.data?.status, query.data?.progress, query.data?.candidate_count]);

  const cancel = useMutation({
    mutationFn: () => endpoints.cancelReviewAttempt(sessionId, selectedId as string),
    onSuccess: (attempt) => { onChanged(attempt); onPreview([]); },
  });
  const expand = useMutation({
    mutationFn: () => endpoints.expandReviewAttempt(sessionId, selectedId as string, revision),
    onSuccess: (attempt) => { onChanged(attempt); setSelectedId(attempt.attempt_id); onPreview([]); },
  });
  const apply = useMutation({
    mutationFn: () => endpoints.applyReviewAttempt(sessionId, selectedId as string, revision, mergeMode),
    onSuccess: (patch) => {
      onApplied(patch.revision, patch.items);
      onPreview([]);
      void client.invalidateQueries({ queryKey: queryKeys.reviewWorkspace(sessionId) });
      message.success(mergeMode === "append" ? "新候选已追加到工作集" : "工作集已由本轮候选替换");
    },
    onError: (error) => message.error(error instanceof Error ? error.message : "应用候选失败"),
  });

  if (!attempts.length || !current) return null;
  return (
    <section className="review-attempt-panel" aria-label="AI 识别进度">
      <div className="review-attempt-panel__header">
        <Space size={8}>
          <Typography.Text strong>识别结果</Typography.Text>
          <Tag color={statusColor(current.status)}>{statusLabel(current.status)}</Tag>
          <Typography.Text type="secondary">候选 {current.candidate_count}</Typography.Text>
        </Space>
        <Select
          size="small"
          value={selectedId}
          options={attempts.map((item, index) => ({ value: item.attempt_id, label: `#${index + 1} · ${item.prompt_type === "text" ? "文本" : "视觉"} · ${statusLabel(item.status)}` }))}
          onChange={setSelectedId}
          style={{ width: 170 }}
        />
      </div>
      <Progress percent={current.progress} status={current.status === "failed" ? "exception" : ["succeeded", "applied"].includes(current.status) ? "success" : "active"} size="small" />
      <Descriptions size="small" column={4} items={[
        { key: "scope", label: "范围", children: current.scope.type === "full" ? "全图" : `${Math.round(current.scope.side_px)} px` },
        { key: "windows", label: "切片", children: `${current.completed_windows}/${current.total_windows}` },
        { key: "skipped", label: "区外跳过", children: current.skipped_windows ?? 0 },
        { key: "elapsed", label: "耗时", children: current.elapsed_seconds == null ? "—" : `${current.elapsed_seconds.toFixed(1)} s` },
      ]} />
      {current.error ? <Alert type="error" showIcon message={current.error} /> : null}
      <Space className="review-attempt-panel__actions">
        {["queued", "running"].includes(current.status) ? <Button danger size="small" icon={<CloseOutlined />} loading={cancel.isPending} onClick={() => cancel.mutate()}>取消</Button> : null}
        {current.status === "succeeded" ? (
          <>
            <Button type="primary" size="small" icon={<CheckOutlined />} loading={apply.isPending} onClick={() => apply.mutate()}>{mergeMode === "append" ? "确认追加" : "确认替换"}</Button>
            {current.scope.type === "region" ? <Button size="small" icon={<ExpandOutlined />} loading={expand.isPending} onClick={() => expand.mutate()}>扩散到全图</Button> : null}
          </>
        ) : null}
      </Space>
    </section>
  );
}

function statusColor(status: ReviewAttempt["status"]): string {
  if (status === "succeeded" || status === "applied") return "success";
  if (status === "failed" || status === "canceled") return "error";
  return "processing";
}

function statusLabel(status: ReviewAttempt["status"]): string {
  return ({ queued: "排队中", running: "识别中", succeeded: "待确认", failed: "失败", canceled: "已取消", applied: "已应用" })[status];
}
