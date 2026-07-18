import { apiDelete, apiGet, apiGetText, apiPatchJson, apiPostForm, apiPostJson, apiPutJson, apiUpload, apiUrl } from "./client";
import type {
  FeatureCollection,
  AssetInspectRequest,
  AssetInspectResult,
  AssetCogConvertResult,
  AssetDeletePreview,
  AssetPatch,
  AssetRow,
  AssetTiffCreate,
  AdminDistrictResult,
  GeoReverseResult,
  GeoSearchResult,
  GeometryKind,
  InputInspectRequest,
  InputInspectResult,
  InferSubmit,
  CancelJobResult,
  CancelAllJobsResult,
  WorkerStopResult,
  ArtifactExportResult,
  ArtifactTree,
  JobHistoryItem,
  JobHistoryQuery,
  JobLogs,
  JobRef,
  JobStatus,
  Tract,
  TractImagery,
  TractSummary,
  TiffAsset,
  TilePreheatRequest,
  TilePreheatResult,
  UploadResponse,
  EffectiveAreaImportResponse,
  EffectiveAreaImportSource,
  EffectiveAreaPutRequest,
  EffectiveAreaResponse,
  ReviewMode,
  ReviewPatch,
  ReviewPublishResult,
  ReviewSession,
  ReviewWorkspace,
  ReviewAttempt,
  ReviewMaskStroke,
} from "./types";

// 端点定义集中一处(DRY)。承接 v1.0 api.ts 的契约, 重构为 FSD shared 层。
export const endpoints = {
  listTracts: (): Promise<Tract[]> => apiGet("/tracts"),

  listTiffs: (): Promise<TiffAsset[]> => apiGet("/tracts/tiffs"),

  getEffectiveArea: (tractPk: string): Promise<EffectiveAreaResponse> =>
    apiGet(`/tracts/${encodeURIComponent(tractPk)}/effective-area`),

  putEffectiveArea: (tractPk: string, body: EffectiveAreaPutRequest): Promise<EffectiveAreaResponse> =>
    apiPutJson(`/tracts/${encodeURIComponent(tractPk)}/effective-area`, body),

  inspectEffectiveAreaImport: (
    tractPk: string,
    source: EffectiveAreaImportSource,
  ): Promise<EffectiveAreaImportResponse> => {
    const body = new FormData();
    for (const file of source.files ?? []) body.append("files", file);
    if (source.localPath) body.append("local_path", source.localPath);
    if (source.layer) body.append("layer", source.layer);
    return apiPostForm(`/tracts/${encodeURIComponent(tractPk)}/effective-area/imports/inspect`, body);
  },

  listReviews: (status?: string): Promise<ReviewSession[]> =>
    apiGet(`/reviews${status ? `?status=${encodeURIComponent(status)}` : ""}`),

  createReview: (body: { phase_id: string; tiff_id: string; mode: ReviewMode; base_run_id?: string }): Promise<ReviewSession> =>
    apiPostJson("/reviews", body),

  getReview: (sessionId: string): Promise<ReviewSession> =>
    apiGet(`/reviews/${encodeURIComponent(sessionId)}`),

  getReviewWorkspace: (sessionId: string): Promise<ReviewWorkspace> =>
    apiGet(`/reviews/${encodeURIComponent(sessionId)}/workspace`),

  reviewPreviewUrl: (sessionId: string): string =>
    apiUrl(`/reviews/${encodeURIComponent(sessionId)}/preview`),

  getReviewCapabilities: (): Promise<Record<string, unknown>> => apiGet("/reviews/capabilities"),

  createReviewAttempt: (
    sessionId: string,
    body: {
      revision: number;
      prompt_type: "text" | "visual";
      prompts: Array<Record<string, unknown>>;
      visual_exemplars: Array<Record<string, unknown>>;
      scope: { type: "viewport" | "full"; bounds?: number[] };
      merge_mode: "append" | "replace_ai_in_scope";
      threshold: number;
    },
  ): Promise<ReviewAttempt> => apiPostJson(`/reviews/${encodeURIComponent(sessionId)}/attempts`, body),

  getReviewAttempt: (sessionId: string, attemptId: string): Promise<ReviewAttempt> =>
    apiGet(`/reviews/${encodeURIComponent(sessionId)}/attempts/${encodeURIComponent(attemptId)}`),

  cancelReviewAttempt: (sessionId: string, attemptId: string): Promise<ReviewAttempt> =>
    apiPostJson(`/reviews/${encodeURIComponent(sessionId)}/attempts/${encodeURIComponent(attemptId)}/cancel`, {}),

  applyReviewAttempt: (
    sessionId: string,
    attemptId: string,
    revision: number,
    mergeMode: "append" | "replace_ai_in_scope",
  ): Promise<ReviewPatch> => apiPostJson(
    `/reviews/${encodeURIComponent(sessionId)}/attempts/${encodeURIComponent(attemptId)}/apply`,
    { revision, merge_mode: mergeMode },
  ),

  expandReviewAttempt: (sessionId: string, attemptId: string, revision: number): Promise<ReviewAttempt> =>
    apiPostJson(
      `/reviews/${encodeURIComponent(sessionId)}/attempts/${encodeURIComponent(attemptId)}/expand`,
      { revision },
    ),

  applyReviewOperations: (
    sessionId: string,
    body: { revision: number; operation_id: string; operations: Array<Record<string, unknown>> },
  ): Promise<ReviewPatch> => apiPostJson(`/reviews/${encodeURIComponent(sessionId)}/operations`, body),

  applyReviewMask: (
    sessionId: string,
    body: { revision: number; operation_id: string; item_id: string; strokes: ReviewMaskStroke[] },
  ): Promise<ReviewPatch> => apiPostJson(`/reviews/${encodeURIComponent(sessionId)}/operations/mask`, body),

  undoReview: (sessionId: string, revision: number, operationId: string): Promise<ReviewPatch> =>
    apiPostJson(`/reviews/${encodeURIComponent(sessionId)}/undo`, { revision, operation_id: operationId }),

  redoReview: (sessionId: string, revision: number, operationId: string): Promise<ReviewPatch> =>
    apiPostJson(`/reviews/${encodeURIComponent(sessionId)}/redo`, { revision, operation_id: operationId }),

  publishReview: (sessionId: string): Promise<ReviewPublishResult> =>
    apiPostJson(`/reviews/${encodeURIComponent(sessionId)}/publish`, {}),

  cancelReview: (sessionId: string, revision: number): Promise<ReviewSession> =>
    apiPostJson(`/reviews/${encodeURIComponent(sessionId)}/cancel`, { revision }),

  listAssets: (): Promise<AssetRow[]> => apiGet("/assets"),

  inspectAssetImage: (body: AssetInspectRequest): Promise<AssetInspectResult> =>
    apiPostJson("/assets/inspect-image", body),

  convertAssetCog: (inputPath: string): Promise<AssetCogConvertResult> =>
    apiPostJson("/assets/convert-cog", { input_path: inputPath }),

  preheatTiffTiles: (
    phaseId: string,
    tiffRef: string,
    body: TilePreheatRequest,
  ): Promise<TilePreheatResult> =>
    apiPostJson(
      `/tiles/tiffs/${encodeURIComponent(phaseId)}/${encodeURIComponent(tiffRef)}/preheat`,
      body,
    ),

  searchGeo: (q: string, city = "广东", limit = 10): Promise<GeoSearchResult> =>
    apiGet(`/geo/search?q=${encodeURIComponent(q)}&city=${encodeURIComponent(city)}&limit=${limit}`),

  reverseGeo: (lng: number, lat: number): Promise<GeoReverseResult> =>
    apiGet(`/geo/reverse?lng=${encodeURIComponent(lng)}&lat=${encodeURIComponent(lat)}`),

  listAdminDistricts: (region = "广东", subdistrict = 3): Promise<AdminDistrictResult> =>
    apiGet(`/geo/admin-districts?region=${encodeURIComponent(region)}&subdistrict=${subdistrict}`),

  createAssetTiff: (body: AssetTiffCreate): Promise<AssetRow[]> =>
    apiPostJson("/assets/tiffs", body),

  patchAssetTract: (tractPk: string, body: AssetPatch): Promise<AssetRow[]> =>
    apiPatchJson(`/assets/tracts/${encodeURIComponent(tractPk)}`, body),

  patchAssetTiff: (phaseId: string, tiffId: string, body: AssetPatch): Promise<AssetRow[]> =>
    apiPatchJson(`/assets/tiffs/${encodeURIComponent(phaseId)}/${encodeURIComponent(tiffId)}`, body),

  deleteAssetTiff: (phaseId: string, tiffId: string, force = false): Promise<AssetRow[]> =>
    apiDelete(`/assets/tiffs/${encodeURIComponent(phaseId)}/${encodeURIComponent(tiffId)}?force=${force ? "true" : "false"}`),

  previewAssetTiffDelete: (phaseId: string, tiffId: string): Promise<AssetDeletePreview> =>
    apiGet(`/assets/tiffs/${encodeURIComponent(phaseId)}/${encodeURIComponent(tiffId)}/delete-preview`),

  getObservations: (
    tractId: string,
    geometry: GeometryKind = "point",
  ): Promise<FeatureCollection> =>
    apiGet(
      `/tracts/${encodeURIComponent(tractId)}/observations?geometry=${geometry}`,
    ),

  getJob: (jobId: string): Promise<JobStatus> =>
    apiGet(`/jobs/${encodeURIComponent(jobId)}`),

  listJobs: ({ taskType = "infer", phaseId, tiffId, limit = 50 }: JobHistoryQuery = {}): Promise<JobHistoryItem[]> => {
    const query = new URLSearchParams({ limit: String(limit) });
    if (taskType) query.set("task_type", taskType);
    if (phaseId) query.set("phase_id", phaseId);
    if (tiffId) query.set("tiff_id", tiffId);
    return apiGet(`/jobs?${query.toString()}`);
  },

  getJobLogs: (jobId: string, cursor = 0): Promise<JobLogs> =>
    apiGet(`/jobs/${encodeURIComponent(jobId)}/logs?cursor=${cursor}`),

  inspectInput: (body: InputInspectRequest): Promise<InputInspectResult> =>
    apiPostJson("/jobs/inspect-input", body),

  // 地块多时相真影像瓦片(时相卷帘刷开真影像)。
  getImagery: (
    tractId: string,
    params?: { phaseId?: string; tiffName?: string },
  ): Promise<TractImagery> => {
    const query = new URLSearchParams();
    if (params?.phaseId) query.set("phase_id", params.phaseId);
    if (params?.tiffName) query.set("tiff_name", params.tiffName);
    const suffix = query.toString() ? "?" + query.toString() : "";
    return apiGet(`/tracts/${encodeURIComponent(tractId)}/imagery${suffix}`);
  },

  getTractSummary: (tractId: string): Promise<TractSummary> =>
    apiGet(`/tracts/${encodeURIComponent(tractId)}/summary`),

  listTractSummaries: (): Promise<TractSummary[]> =>
    apiGet("/tracts/summaries"),

  // 上传影像(multipart, 带进度) -> 存储 key。
  uploadImage: (
    file: File,
    onProgress?: (percent: number) => void,
  ): Promise<UploadResponse> => apiUpload("/uploads", file, onProgress),

  // 提交异步推理作业 -> 202 + job_id。
  submitInfer: (body: InferSubmit): Promise<JobRef> =>
    apiPostJson("/jobs/infer", body),

  cancelJob: (jobId: string): Promise<CancelJobResult> =>
    apiPostJson(`/jobs/${encodeURIComponent(jobId)}/cancel`, {}),

  cancelAllJobs: (): Promise<CancelAllJobsResult> =>
    apiPostJson("/jobs/cancel-all", {}),

  stopWorker: (): Promise<WorkerStopResult> =>
    apiPostJson("/jobs/stop-worker", {}),

  getArtifacts: (jobId: string): Promise<ArtifactTree> =>
    apiGet(`/jobs/${encodeURIComponent(jobId)}/artifacts`),

  previewArtifactUrl: (jobId: string, path: string): string =>
    apiUrl(`/jobs/${encodeURIComponent(jobId)}/artifacts/file?path=${encodeURIComponent(path)}`),

  getArtifactText: (jobId: string, path: string): Promise<string> =>
    apiGetText(`/jobs/${encodeURIComponent(jobId)}/artifacts/file?path=${encodeURIComponent(path)}`),

  downloadArtifactPathUrl: (jobId: string, path: string): string =>
    apiUrl(`/jobs/${encodeURIComponent(jobId)}/artifacts/download?path=${encodeURIComponent(path)}`),

  exportArtifacts: (jobId: string, paths: string[]): Promise<ArtifactExportResult> =>
    apiPostJson(`/jobs/${encodeURIComponent(jobId)}/artifacts/export`, { paths }),

  downloadArtifactUrl: (url: string): string => apiUrl(url.replace(/^\/api\/v1/, "")),

  // 报告/导出为文件下载, 直接用链接打开。
  reportUrl: (tractId: string, fmt = "pdf"): string =>
    apiUrl(`/tracts/${encodeURIComponent(tractId)}/report?fmt=${fmt}`),

  exportUrl: (tractId: string, fmt = "geojson"): string =>
    apiUrl(`/tracts/${encodeURIComponent(tractId)}/export?fmt=${fmt}`),
} as const;
