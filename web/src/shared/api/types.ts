// 后端契约的前端镜像类型(与 Python contracts/schemas 对应)。单一真相集中在此。
export interface Tract {
  tract_phase_pk?: string;
  phase_id?: string;
  region_id?: string;
  city?: string | null;
  county?: string | null;
  town?: string | null;
  tract_id: string;
  geo_area?: number;
  area_unit?: string;
  crs_epsg?: number;
  active_run_id?: string;
  observation_count?: number;
  // 地块代表点经纬度(WGS84)。由 /tracts 从地理观测中心回填, 用于倒水滴标记。
  center_lng?: number;
  center_lat?: number;
  [k: string]: unknown;
}

export type JobState = "queued" | "running" | "succeeded" | "failed" | "canceled";

export interface JobStatus {
  job_id: string;
  status: JobState;
  tract_id?: string;
  started_at?: string;
  ended_at?: string;
  duration_s?: number;
  error?: string;
  metrics?: Record<string, unknown>;
}

export interface JobLogs {
  job_id: string;
  cursor: number;
  lines: string[];
  available: boolean;
}

export interface JobHistoryItem {
  run_id: string;
  task_type: string;
  status: JobState;
  model_arch?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  duration_s?: number | null;
  input_path?: string | null;
  tract_id?: string | null;
  geo_area?: number | null;
  area_unit?: string | null;
  observation_count: number;
  error?: string | null;
  metrics?: Record<string, unknown>;
}

export interface CancelJobResult {
  job_id: string;
  status: JobState;
  message: string;
}

export interface CancelAllJobsResult {
  cancelled: number;
  purged_queues: string[];
  message: string;
}

export interface ArtifactNode {
  key: string;
  name: string;
  path: string;
  type: "directory" | "file" | string;
  size?: number | null;
  previewable: boolean;
  description?: string | null;
  children?: ArtifactNode[];
}

export interface ArtifactTree {
  run_id: string;
  run_dir?: string | null;
  available: boolean;
  tree: ArtifactNode[];
}

export interface ArtifactExportResult {
  run_id: string;
  filename: string;
  url: string;
}

// 上传响应(对应 schemas.UploadResponse)。key 回传给 /jobs/infer。
export interface UploadResponse {
  key: string;
  filename: string;
  size: number;
}

// 提交推理作业的请求体(对应 schemas.InferSubmit)。
export interface InferSubmit {
  image_key?: string;
  input_path?: string;
  arch?: string;
  phase_id?: string;
  tract_id?: string;
  tile_size?: number;
  overlap_rate?: number;
  dsm?: string;
  dem?: string;
  las?: string;
  export_fmt?: string;
}

// 作业引用(对应 schemas.JobRef)。
export interface JobRef {
  job_id: string;
  status: JobState;
}

export interface InputInspectRequest {
  input_path: string;
}

export interface InputInspectImage {
  path: string;
  stem: string;
  width?: number | null;
  height?: number | null;
  crs_epsg?: number | null;
  phase_id?: string | null;
  phase_source?: string | null;
}

export interface InputInspectResult {
  input_path: string;
  normalized_path: string;
  input_kind: "file" | "directory" | string;
  image_count: number;
  suggested_tract_id?: string | null;
  suggested_phase_id?: string | null;
  images: InputInspectImage[];
}

export interface AssetRow {
  city?: string | null;
  county?: string | null;
  town?: string | null;
  region_id?: string | null;
  tract_pk?: string | null;
  tract_id?: string | null;
  tract_phase_pk?: string | null;
  phase_id?: string | null;
  tiff_id?: string | null;
  image_name?: string | null;
  source_path?: string | null;
  run_id?: string | null;
  status: string;
  geo_area?: number | null;
  area_unit?: string | null;
  observation_count: number;
  detected_at?: string | null;
}

export interface AssetInspectRequest {
  input_path?: string;
  lng?: number;
  lat?: number;
}

export interface AssetInspectResult {
  input_path?: string | null;
  normalized_path?: string | null;
  exists: boolean;
  inspect_error?: string | null;
  image_name?: string | null;
  suggested_tract_id?: string | null;
  suggested_phase_id?: string | null;
  city?: string | null;
  county?: string | null;
  town?: string | null;
  region_id?: string | null;
  lng?: number | null;
  lat?: number | null;
  width?: number | null;
  height?: number | null;
  crs_epsg?: number | null;
  geo_error?: string | null;
}

export interface AssetTiffCreate {
  input_path: string;
  city?: string | null;
  county?: string | null;
  town?: string | null;
  tract_id?: string | null;
  phase_id?: string | null;
  image_name?: string | null;
}

export interface AssetPatch {
  city?: string | null;
  county?: string | null;
  town?: string | null;
  tract_id?: string | null;
  phase_id?: string | null;
  image_name?: string | null;
  new_path?: string | null;
}

export type GeometryKind = "point" | "crown";

export interface GeoPlace {
  id: string;
  name: string;
  address?: string | null;
  city?: string | null;
  county?: string | null;
  town?: string | null;
  adcode?: string | null;
  lng: number;
  lat: number;
  source: string;
}

export interface GeoSearchResult {
  query: string;
  places: GeoPlace[];
}

export interface GeoReverseResult {
  lng: number;
  lat: number;
  city: string;
  county: string;
  town: string;
  region_id: string;
  formatted_address?: string | null;
  adcode?: string | null;
}

export interface GeoFeature {
  type: "Feature";
  geometry: unknown;
  properties: Record<string, unknown>;
}

export interface FeatureCollection {
  type: "FeatureCollection";
  features: GeoFeature[];
}

// 地块多时相真影像瓦片(对应 schemas.TractImageryOut)。
// tiles 为空 / available=false 时, 前端回退默认底图。
export interface TractImagery {
  tract_id: string;
  phase_id?: string;
  tiles?: string[] | null;
  tile_size?: number;
  attribution?: string | null;
  min_zoom?: number | null;
  max_zoom?: number | null;
  available: boolean;
  source_path?: string | null;
  source_format?: string | null;
  tile_service?: string | null;
}

export interface DistributionSummary {
  n?: number;
  min?: number;
  max?: number;
  mean?: number;
  median?: number;
  p10?: number;
  p90?: number;
  std?: number;
}

export interface SpeciesAnalysis {
  count?: number;
  ratio?: number;
  ra?: number;
  rc?: number;
  iv?: number;
  fi?: number | null;
  density_per_ha?: number | null;
  total_crown_area?: number;
  total_volume?: number;
  avg_height?: number | null;
  max_height?: number | null;
  avg_volume?: number | null;
  max_volume?: number | null;
  avg_crown_area?: number | null;
  crown_width_geo?: DistributionSummary;
  crown_height_geo?: DistributionSummary;
  crown_area_geo?: DistributionSummary;
  height?: DistributionSummary;
}

export interface TractSummary {
  tract_id?: string | null;
  tract_phase_pk?: string | null;
  phase_id?: string | null;
  run_id?: string | null;
  tree_count: number;
  species: Record<string, number>;
  density_per_ha?: number | null;
  crown_width_geo?: DistributionSummary;
  crown_height_geo?: DistributionSummary;
  crown_area_geo?: DistributionSummary;
  height?: DistributionSummary;
  meta?: {
    phase_id?: string | null;
    area_m2?: number | null;
    species_richness?: number;
    species_analysis?: Record<string, SpeciesAnalysis>;
    canopy_cover_rate?: number | null;
    total_crown_area?: number;
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
