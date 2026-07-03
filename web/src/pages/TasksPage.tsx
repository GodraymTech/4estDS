import { PageContainer } from "../shared/ui/PageContainer";

// 任务中心: 影像上传 → 推理作业队列 → 状态追踪(P1, 复用 useJob 轮询)。
export function TasksPage() {
  return (
    <PageContainer
      title="任务中心"
      subtitle="上传影像、发起推理作业并追踪进度与耗时。"
      phase="P1"
    />
  );
}
