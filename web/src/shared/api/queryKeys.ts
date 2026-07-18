import type { GeometryKind } from "./types";

// TanStack Query 键工厂(单一真相): 避免字符串散布导致缓存失效不一致。
export const queryKeys = {
  tracts: ["tracts"] as const,
  tiffs: ["tiffs"] as const,
  assets: ["assets"] as const,
  geoSearch: (q: string, city = "广东") => ["geo-search", city, q] as const,
  observations: (tractId: string, geometry: GeometryKind) =>
    ["observations", tractId, geometry] as const,
  jobs: (taskType: string | null = "infer", phaseId?: string, tiffId?: string) =>
    ["jobs", taskType ?? "all", phaseId ?? "", tiffId ?? ""] as const,
  job: (jobId: string) => ["job", jobId] as const,
  imagery: (tractId: string, phaseId?: string, tiffRef?: string) =>
    ["imagery", tractId, phaseId ?? "", tiffRef ?? ""] as const,
  tractSummary: (tractId: string) => ["tract-summary", tractId] as const,
  tractSummaries: ["tract-summaries"] as const,
  effectiveArea: (tractPk: string) => ["effective-area", tractPk] as const,
  reviews: ["reviews"] as const,
  review: (sessionId: string) => ["review", sessionId] as const,
  reviewWorkspace: (sessionId: string) => ["review-workspace", sessionId] as const,
};
