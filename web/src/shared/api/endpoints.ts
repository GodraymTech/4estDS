import { apiGet, apiPostJson, apiUpload, apiUrl } from "./client";
import type {
  FeatureCollection,
  GeometryKind,
  InferSubmit,
  JobRef,
  JobStatus,
  Tract,
  UploadResponse,
} from "./types";

// 端点定义集中一处(DRY)。承接 v1.0 api.ts 的契约, 重构为 FSD shared 层。
export const endpoints = {
  listTracts: (): Promise<Tract[]> => apiGet("/tracts"),

  getObservations: (
    tractId: string,
    geometry: GeometryKind = "point",
  ): Promise<FeatureCollection> =>
    apiGet(
      `/tracts/${encodeURIComponent(tractId)}/observations?geometry=${geometry}`,
    ),

  getJob: (jobId: string): Promise<JobStatus> =>
    apiGet(`/jobs/${encodeURIComponent(jobId)}`),

  // 上传影像(multipart, 带进度) -> 存储 key。
  uploadImage: (
    file: File,
    onProgress?: (percent: number) => void,
  ): Promise<UploadResponse> => apiUpload("/uploads", file, onProgress),

  // 提交异步推理作业 -> 202 + job_id。
  submitInfer: (body: InferSubmit): Promise<JobRef> =>
    apiPostJson("/jobs/infer", body),

  // 报告/导出为文件下载, 直接用链接打开。
  reportUrl: (tractId: string, fmt = "pdf"): string =>
    apiUrl(`/tracts/${encodeURIComponent(tractId)}/report?fmt=${fmt}`),

  exportUrl: (tractId: string, fmt = "geojson"): string =>
    apiUrl(`/tracts/${encodeURIComponent(tractId)}/export?fmt=${fmt}`),
} as const;
