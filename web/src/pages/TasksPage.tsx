import { PageContainer } from "../shared/ui/PageContainer";
import { TasksCenter } from "../features/tasks";

// 任务中心: 参数配置 → 推理作业队列 → 日志与指标追踪。
export function TasksPage() {
  return (
    <PageContainer
      title="任务中心"
      subtitle="配置推理参数、提交单图或批量任务，并追踪日志、指标与输出。"
    >
      <TasksCenter />
    </PageContainer>
  );
}
