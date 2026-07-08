import type { GeometryKind } from "./types";

// TanStack Query 键工厂(单一真相): 避免字符串散布导致缓存失效不一致。
export const queryKeys = {
  tracts: ["tracts"] as const,
  assets: ["assets"] as const,
  geoSearch: (q: string, city = "广东") => ["geo-search", city, q] as const,
  observations: (tractId: string, geometry: GeometryKind) =>
    ["observations", tractId, geometry] as const,
  jobs: (taskType = "infer") => ["jobs", taskType] as const,
  job: (jobId: string) => ["job", jobId] as const,
  imagery: (tractId: string) => ["imagery", tractId] as const,
  tractSummary: (tractId: string) => ["tract-summary", tractId] as const,
  tractSummaries: ["tract-summaries"] as const,
};
