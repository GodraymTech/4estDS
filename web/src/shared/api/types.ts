// 后端契约的前端镜像类型(与 Python contracts/schemas 对应)。单一真相集中在此。
export interface Tract {
  tract_id: string;
  name?: string;
  acquisition_time?: string;
  location?: string;
  geo_area?: number;
  area_unit?: string;
  crs_epsg?: number;
  active_run_id?: string;
  // 地块代表点经纬度(WGS84)。用于总览图倒水滴标记。
  // TODO(后端契约): /tracts 应由存储的地块几何质心回填此两个字段(代价极低)。
  center_lng?: number;
  center_lat?: number;
  [k: string]: unknown;
}

export type JobState = "queued" | "running" | "succeeded" | "failed";

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

// 上传响应(对应 schemas.UploadResponse)。key 回传给 /jobs/infer。
export interface UploadResponse {
  key: string;
  filename: string;
  size: number;
}

// 提交推理作业的请求体(对应 schemas.InferSubmit)。
export interface InferSubmit {
  image_key: string;
  arch?: string;
  acquisition_time?: string; // YYYYmmdd
  location?: string;
  tile_size?: number;
  overlap_rate?: number;
  export_fmt?: string;
}

// 作业引用(对应 schemas.JobRef)。
export interface JobRef {
  job_id: string;
  status: JobState;
}

export type GeometryKind = "point" | "crown";

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
  acquisition_time?: string;
  tiles?: string[] | null;
  tile_size?: number;
  attribution?: string | null;
  min_zoom?: number | null;
  max_zoom?: number | null;
  available: boolean;
}
