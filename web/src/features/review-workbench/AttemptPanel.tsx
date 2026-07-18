import { useEffect, useState } from "react";
import { Alert, Button, Descriptions, Progress, Select, Space, Tag, message } from "antd";
import { CheckOutlined, CloseOutlined, ExpandOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReviewAttempt, ReviewItem } from "../../entities/review";
import { endpoints, queryKeys } from "../../shared/api";

export function AttemptPanel({ sessionId, revision, attempts, onChanged, onApplied }: {
  sessionId: string;
  revision: number;
  attempts: ReviewAttempt[];
  onChanged: (attempt: ReviewAttempt) => void;
  onApplied: (revision: number, items: ReviewItem[]) => void;
}) {
  const client = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | undefined>(attempts[attempts.length - 1]?.attempt_id);
  useEffect(() => { if (!selectedId && attempts.length) setSelectedId(attempts[attempts.length - 1]?.attempt_id); }, [attempts.length]);
  const query = useQuery({
    queryKey: ["review-attempt", sessionId, selectedId],
    queryFn: () => endpoints.getReviewAttempt(sessionId, selectedId as string),
    enabled: Boolean(selectedId),
    refetchInterval: (state) => ["queued", "running"].includes(state.state.data?.status ?? "") ? 1000 : false,
  });
  useEffect(() => { if (query.data) onChanged(query.data); }, [query.data?.status, query.data?.progress, query.data?.candidate_count]);
  const current = query.data ?? attempts.find((item) => item.attempt_id === selectedId);

  const cancel = useMutation({ mutationFn: () => endpoints.cancelReviewAttempt(sessionId, selectedId as string), onSuccess: onChanged });
  const expand = useMutation({
    mutationFn: () => endpoints.expandReviewAttempt(sessionId, selectedId as string, revision),
    onSuccess: (attempt) => { onChanged(attempt); setSelectedId(attempt.attempt_id); },
  });
  const apply = useMutation({
    mutationFn: (mode: "append" | "replace_ai_in_scope") => endpoints.applyReviewAttempt(sessionId, selectedId as string, revision, mode),
    onSuccess: (patch) => {
      onApplied(patch.revision, patch.items);
      void client.invalidateQueries({ queryKey: queryKeys.reviewWorkspace(sessionId) });
      message.success("候选已合并到工作集");
    },
    onError: (error) => message.error(error instanceof Error ? error.message : "应用候选失败"),
  });

  if (!attempts.length) return null;
  return (
    <section>
      <h3>Attempt</h3>
      <Select value={selectedId} options={attempts.map((item) => ({ value: item.attempt_id, label: `${item.prompt_type} · ${item.scope.type} · ${item.status}` }))} onChange={setSelectedId} />
      {current ? (
        <>
          <Space><Tag color={statusColor(current.status)}>{current.status}</Tag><span>候选 {current.candidate_count}</span></Space>
          <Progress percent={current.progress} status={current.status === "failed" ? "exception" : current.status === "succeeded" || current.status === "applied" ? "success" : "active"} />
          <Descriptions size="small" column={1} items={[
            { key: "scope", label: "范围", children: current.scope.type },
            { key: "windows", label: "窗口", children: `${current.completed_windows}/${current.total_windows}` },
            { key: "merge", label: "默认合并", children: current.merge_mode },
          ]} />
          {current.error ? <Alert type="error" showIcon message={current.error} /> : null}
          <Space wrap>
            {current.status === "queued" || current.status === "running" ? <Button danger icon={<CloseOutlined />} loading={cancel.isPending} onClick={() => cancel.mutate()}>取消</Button> : null}
            {current.status === "succeeded" ? (
              <>
                <Button icon={<CheckOutlined />} loading={apply.isPending} onClick={() => apply.mutate("append")}>追加</Button>
                <Button loading={apply.isPending} onClick={() => apply.mutate("replace_ai_in_scope")}>替换范围 AI</Button>
                {current.scope.type === "viewport" ? <Button icon={<ExpandOutlined />} loading={expand.isPending} onClick={() => expand.mutate()}>扩散到全图</Button> : null}
              </>
            ) : null}
          </Space>
        </>
      ) : null}
    </section>
  );
}

function statusColor(status: ReviewAttempt["status"]): string {
  if (status === "succeeded" || status === "applied") return "success";
  if (status === "failed" || status === "canceled") return "error";
  return "processing";
}
