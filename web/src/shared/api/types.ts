// 后端契约的前端镜像类型(与 Python contracts 对应)。单一真相集中在此。
export interface Tract {
  tract_id: string;
  name?: string;
  acquisition_time?: string;
  location?: string;
  geo_area?: number;
  area_unit?: string;
  crs_epsg?: number;
  active_run_id?: string;
  [k: string]: unknown;
}

export type JobState = "queued" | "running" | "succeeded" | "failed";

export interface JobStatus {
  job_id: string;
  status: JobState;
  tract_id?: string;
  duration_s?: number;
  error?: string;
  metrics?: Record<string, unknown>;
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
