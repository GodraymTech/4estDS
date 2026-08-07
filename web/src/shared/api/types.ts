// 后端契约的前端镜像类型(与 Python contracts/schemas 对应)。单一真相集中在此。
export interface Tract {
  tract_pk?: string;
  tract_phase_pk?: string;
  phase_id?: string;
  region_id?: string;
  city?: string | null;
  county?: string | null;
  town?: string | null;
  tract_id: string;
  geo_area?: number;
  tract_area_hm2?: number | null;
  tract_phase_area_hm2?: number | null;
  effective_area_hm2?: number | null;
  area_unit?: string;
  crs_epsg?: number;
  active_run_id?: string;
  observation_count?: number;
  // 地块代表点经纬度(WGS84)。由 /tracts 从地理观测中心回填, 用于倒水滴标记。
  center_lng?: number;
  center_lat?: number;
  [k: string]: unknown;
}

export interface TiffAsset {
  tract_pk?: string;
  city?: string | null;
  county?: string | null;
  town?: string | null;
  tract_id: string;
  tract_phase_pk: string;
  phase_id: string;
  tiff_id: string;
  file_name?: string | null;
  source_path?: string | null;
  path_exists: boolean;
  tiff_type?: "normal" | "tiled" | "ext_ovr" | "COG" | "invalid" | null;
  footprint_bbox?: string | null;
  center_geom?: string | null;
  center_lng?: number | null;
  center_lat?: number | null;
  crs_epsg?: number | null;
  crs_wkt?: string | null;
  geotransform?: string | null;
  pixel_width?: number | null;
  pixel_height?: number | null;
  gsd?: number | null;
  geo_area?: number | null;
  tract_area_hm2?: number | null;
  area_unit?: string | null;
  band_count?: number | null;
  dtype?: string | null;
  nodata?: number | null;
  observation_count: number;
  status: string;
  has_detection: boolean;
  active_run_id?: string | null;
  run_id?: string | null;
  run_count: number;
  run_status_counts: Partial<Record<JobState, number>>;
  active_run_status?: JobState | null;
  detected_at?: string | null;
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
  phase_id?: string | null;
  tiff_id?: string | null;
  geo_area?: number | null;
  effective_area_hm2?: number | null;
  area_unit?: string | null;
  observation_count: number;
  error?: string | null;
  metrics?: Record<string, unknown>;
}

export interface JobHistoryQuery {
  taskType?: string | null;
  phaseId?: string;
  tiffId?: string;
  limit?: number;
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

export interface WorkerStopResult extends CancelAllJobsResult {
  worker_pids: number[];
  worker_found: boolean;
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
  tiff_type?: "normal" | "tiled" | "ext_ovr" | "COG" | "invalid" | null;
  active_run_id?: string | null;
  run_id?: string | null;
  run_count: number;
  run_status_counts: Partial<Record<JobState, number>>;
  active_run_status?: JobState | null;
  status: string;
  geo_area?: number | null;
  area_hm2?: number | null;
  tract_area_hm2?: number | null;
  tract_phase_area_hm2?: number | null;
  effective_area_hm2?: number | null;
  area_unit?: string | null;
  observation_count: number;
  detected_at?: string | null;
  pixel_width?: number | null;
  pixel_height?: number | null;
  estimated_cog_seconds?: number | null;
}

export interface AssetDeletePreview {
  phase_id: string;
  tiff_id: string;
  observation_count: number;
  requires_confirmation: boolean;
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
  tiff_type?: "normal" | "tiled" | "ext_ovr" | "COG" | "invalid" | null;
  tiff_type_label?: string | null;
  cog_required?: boolean;
  suggested_cog_path?: string | null;
  suggested_cog_display_path?: string | null;
  geo_error?: string | null;
  estimated_cog_seconds?: number | null;
}

export interface AssetCogConvertResult {
  input_path: string;
  source_path: string;
  source_display_path: string;
  cog_path: string;
  cog_display_path: string;
  tiff_type: "normal" | "tiled" | "ext_ovr" | "COG" | "invalid";
  tiff_type_label: string;
  converted: boolean;
}

export interface TilePreheatRequest {
  bounds: [[number, number], [number, number]];
  zoom: number;
  include_adjacent_zooms?: boolean;
}

export interface TilePreheatResult {
  accepted: number;
  cached: number;
  skipped: number;
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
  tiff_type?: "normal" | "tiled" | "ext_ovr" | "COG" | "invalid" | null;
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

export interface AdminDistrict {
  name: string;
  adcode?: string | null;
  level?: string | null;
  districts?: AdminDistrict[];
}

export interface AdminDistrictResult {
  region: string;
  districts: AdminDistrict[];
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

export type EffectiveAreaPosition = number[];
export type EffectiveAreaRing = EffectiveAreaPosition[];

export interface EffectiveAreaPolygon {
  type: "Polygon";
  coordinates: EffectiveAreaRing[];
}

export interface EffectiveAreaMultiPolygon {
  type: "MultiPolygon";
  coordinates: EffectiveAreaRing[][];
}

export type EffectiveAreaGeometry = EffectiveAreaPolygon | EffectiveAreaMultiPolygon;

export interface EffectiveAreaResponse {
  tract_pk: string;
  boundary_geometry: EffectiveAreaGeometry;
  geometry: EffectiveAreaGeometry;
  tract_area_hm2: number;
  tract_phase_area_hm2?: number;
  effective_area_hm2: number;
  effective_ratio: number;
  updated_at: string;
  warnings: string[];
  is_default: boolean;
}

export interface EffectiveAreaPutRequest {
  geometry: EffectiveAreaGeometry;
  updated_at: string;
  clip_to_boundary?: boolean;
}

export interface EffectiveAreaImportSource {
  files?: File[];
  localPath?: string;
  layer?: string;
}

export interface EffectiveAreaImportResponse {
  tract_pk: string;
  geometry: EffectiveAreaGeometry;
  source_crs: string;
  target_crs: string;
  feature_count: number;
  polygon_count: number;
  layer: string | null;
  layers: string[];
  effective_area_hm2: number;
  effective_ratio: number;
  requires_clip: boolean;
  warnings: string[];
}

export type ReviewMode = "inherit" | "fresh";
export type ReviewItemStatus = "accepted" | "rejected" | "pending";

export interface ReviewMaskRle {
  height: number;
  width: number;
  counts: number[];
}

export interface ReviewMaskGeometry {
  type: "Polygon" | "MultiPolygon";
  coordinates: number[][][] | number[][][][];
}

export interface ReviewMaskStroke {
  mode: "add" | "erase";
  x: number;
  y: number;
  radius: number;
}

export interface ReviewItem {
  id: string;
  parent_observation_id?: string | null;
  individual_id?: string | null;
  species: string;
  confidence?: number | null;
  box_px: number[];
  box_geo?: number[] | null;
  /** 地图渲染专用 EPSG:4326 外接框，由后端从 box_px 精确派生。 */
  box_wgs84?: number[] | null;
  center_geom?: string | null;
  crown_geom?: string | null;
  mask_rle?: ReviewMaskRle;
  source_window?: number[];
  mask_geometry_px?: ReviewMaskGeometry;
  source: "parent" | "human" | "ai";
  confirmed: boolean;
  status: ReviewItemStatus;
  note?: string;
  conflict?: boolean;
  /** 冻结框: 上一轮已并入工作集的存量框。不可删除, 几何与树种锁定, 仅可改判定与备注。 */
  frozen?: boolean;
}

export interface ReviewCategory {
  id: string;
  display_name: string;
  model_prompt: string;
  color: string;
}

export interface ReviewSession {
  session_id: string;
  phase_id: string;
  tiff_id: string;
  tract_phase_pk: string;
  mode: ReviewMode;
  base_run_id?: string | null;
  expected_active_run_id?: string | null;
  status: "active" | "published" | "canceled";
  revision: number;
  published_run_id?: string | null;
  created_at: string;
  updated_at: string;
  image_name?: string | null;
  city?: string | null;
  tract_id?: string | null;
}

export interface ReviewWorkspace {
  revision: number;
  items: ReviewItem[];
  category_catalog: ReviewCategory[];
  visible_categories: string[];
  active_category?: string | null;
  text_prompts: Array<Record<string, unknown>>;
  visual_exemplars: Array<Record<string, unknown>>;
  attempts: ReviewAttempt[];
  total_items?: number;
  page_offset?: number;
  page_limit?: number | null;
}

export interface ReviewPatch {
  session_id: string;
  revision: number;
  items: ReviewItem[];
  summary: Record<string, number>;
  changed_items: ReviewItem[];
  deleted_item_ids: string[];
  replace_all: boolean;
}

export interface ReviewPublishResult {
  session_id: string;
  run_id: string;
  observation_count: number;
  status: string;
}

/** AI 识别范围: 以地图中心为基准的正方形像素区域, 或整图。 */
export type ReviewScope =
  | { type: "region"; center_px: [number, number]; side_px: number }
  | { type: "full" };

export type ReviewMergeMode = "append" | "replace_all";

export interface ReviewAttempt {
  attempt_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "canceled" | "applied";
  prompt_type: "text" | "visual";
  prompts?: Array<Record<string, unknown>>;
  visual_exemplars?: Array<Record<string, unknown>>;
  scope: ReviewScope;
  merge_mode: ReviewMergeMode;
  threshold: number;
  progress: number;
  completed_windows: number;
  total_windows: number;
  candidate_count: number;
  candidates: ReviewItem[];
  parent_attempt_id?: string | null;
  error?: string | null;
  /** 落在有效区域外被跳过的切片数。 */
  skipped_windows?: number;
  /** 中心点落在有效区域外被丢弃的检测框数。 */
  dropped_outside?: number;
  /** 推理耗时(秒)。 */
  elapsed_seconds?: number;
}

export interface ReviewCapabilities {
  name: string;
  available?: boolean;
  segmentation?: boolean;
  defaults: {
    scope: ReviewScope["type"];
    merge_mode: ReviewMergeMode;
    threshold: number;
  };
  limits: {
    viewport_max_windows: number;
    max_candidates_per_attempt: number;
    bbox_page_size: number;
  };
  [key: string]: unknown;
}

export interface ReviewMapContext {
  phase_id: string;
  tiff_id: string;
  tract_pk?: string | null;
  pixel_width: number;
  pixel_height: number;
  gsd: number;
  bounds_wgs84: [number, number, number, number];
  /** 左上、右上、右下、左下；用于局部双线性像素/经纬度换算。 */
  corner_wgs84: [[number, number], [number, number], [number, number], [number, number]];
  effective_geometry?: EffectiveAreaGeometry | null;
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
  p25?: number;
  p75?: number;
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
  crown_size_geo?: DistributionSummary;
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
  crown_size_geo?: DistributionSummary;
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


export interface ServerFileItem {
  name: string;
  path: string;
  is_dir: boolean;
  size?: number | null;
}

export interface ServerFileBrowseOut {
  current_path: string;
  parent_path?: string | null;
  items: ServerFileItem[];
}
