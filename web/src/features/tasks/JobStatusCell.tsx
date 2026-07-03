import { Space, Spin, Tag, Tooltip } from "antd";
import { useJob, type JobState } from "../../entities/run";

const META: Record<JobState, { color: string; text: string }> = {
  queued: { color: "default", text: "排队中" },
  running: { color: "processing", text: "推理中" },
  succeeded: { color: "success", text: "已完成" },
  failed: { color: "error", text: "失败" },
};

// 单行作业状态: 自行轮询(useJob 在终态停止)。
export function JobStatusCell({ jobId }: { jobId: string }) {
  const { data } = useJob(jobId);
  const status: JobState = data?.status ?? "queued";
  const meta = META[status];
  const active = status === "queued" || status === "running";
  return (
    <Space size={6}>
      {active ? <Spin size="small" /> : null}
      {status === "failed" && data?.error ? (
        <Tooltip title={data.error}>
          <Tag color={meta.color}>{meta.text}</Tag>
        </Tooltip>
      ) : (
        <Tag color={meta.color}>{meta.text}</Tag>
      )}
      {status === "succeeded" && typeof data?.duration_s === "number" ? (
        <span style={DURATION}>{data.duration_s.toFixed(1)}s</span>
      ) : null}
    </Space>
  );
}

const DURATION = {
  fontSize: 12,
  fontVariantNumeric: "tabular-nums" as const,
  color: "var(--color-text-muted, #5c6b66)",
};
