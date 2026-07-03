import type { GeometryKind } from "./types";

// TanStack Query 键工厂(单一真相): 避免字符串散布导致缓存失效不一致。
export const queryKeys = {
  tracts: ["tracts"] as const,
  observations: (tractId: string, geometry: GeometryKind) =>
    ["observations", tractId, geometry] as const,
  job: (jobId: string) => ["job", jobId] as const,
};
