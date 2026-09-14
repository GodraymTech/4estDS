import type { GeometryKind } from "./types";

// TanStack Query 键工厂(单一真相): 避免字符串散布导致缓存失效不一致。
export const queryKeys = {
  tracts: ["tracts"] as const,
  tiffs: ["tiffs"] as const,
  assets: ["assets"] as const,
  geoSearch: (q: string, city = "广东") => ["geo-search", city, q] as const,
  observations: (
    tractId: string,
    geometry: GeometryKind,
    options?: { tiffId?: string; phaseId?: string; tiffName?: string },
  ) =>
    ["observations", tractId, geometry, options?.tiffId ?? "", options?.phaseId ?? "", options?.tiffName ?? ""] as const,
  // 前缀键: 用于一次性失效全部作业列表(不必关心当前筛选组合)。
  jobsAll: ["jobs"] as const,
  jobs: (taskType: string | null = "infer", phaseId?: string, tiffId?: string) =>
    ["jobs", taskType ?? "all", phaseId ?? "", tiffId ?? ""] as const,
  job: (jobId: string) => ["job", jobId] as const,
  jobLogs: (jobId: string, cursor: number) => ["job-logs", jobId, cursor] as const,
  imagery: (tractId: string, phaseId?: string, tiffRef?: string) =>
    ["imagery", tractId, phaseId ?? "", tiffRef ?? ""] as const,
  tractSummary: (tractId: string) => ["tract-summary", tractId] as const,
  tractSummaries: ["tract-summaries"] as const,
  effectiveArea: (tractPk: string) => ["effective-area", tractPk] as const,
  reviews: ["reviews"] as const,
  review: (sessionId: string) => ["review", sessionId] as const,
  reviewWorkspace: (sessionId: string) => ["review-workspace", sessionId] as const,
  treeObservations: (params: Record<string, unknown>) => ["tree-observations", params] as const,
};
