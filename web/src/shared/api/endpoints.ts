import { apiDelete, apiGet, apiGetText, apiPatchJson, apiPostJson, apiUpload, apiUrl } from "./client";
import type {
  FeatureCollection,
  AssetInspectRequest,
  AssetInspectResult,
  AssetCogConvertResult,
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
  ArtifactExportResult,
  ArtifactTree,
  JobHistoryItem,
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
} from "./types";

// 端点定义集中一处(DRY)。承接 v1.0 api.ts 的契约, 重构为 FSD shared 层。
export const endpoints = {
  listTracts: (): Promise<Tract[]> => apiGet("/tracts"),

  listTiffs: (): Promise<TiffAsset[]> => apiGet("/tracts/tiffs"),

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

  getObservations: (
    tractId: string,
    geometry: GeometryKind = "point",
  ): Promise<FeatureCollection> =>
    apiGet(
      `/tracts/${encodeURIComponent(tractId)}/observations?geometry=${geometry}`,
    ),

  getJob: (jobId: string): Promise<JobStatus> =>
    apiGet(`/jobs/${encodeURIComponent(jobId)}`),

  listJobs: (taskType = "infer", limit = 50): Promise<JobHistoryItem[]> =>
    apiGet(`/jobs?task_type=${encodeURIComponent(taskType)}&limit=${limit}`),

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
