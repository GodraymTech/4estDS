import { useQuery } from "@tanstack/react-query";
import { endpoints, queryKeys, type JobStatus } from "../../shared/api";

// 作业状态轮询: running/queued 时每 3s 轮询, 终态停止。
export function useJob(jobId: string | undefined) {
  return useQuery<JobStatus>({
    queryKey: queryKeys.job(jobId ?? ""),
    queryFn: () => endpoints.getJob(jobId as string),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s === "succeeded" || s === "failed" ? false : 3000;
    },
  });
}
