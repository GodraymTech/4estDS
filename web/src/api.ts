// 4estDS API 客户端 (单一职责: 封装 HTTP 调用, 前端其他部分不直接接触 fetch)。
export const API_BASE = import.meta.env.VITE_API_BASE || "/api/v1"

export interface Tract {
  tract_id: string
  name?: string
  acquisition_time?: string
  location?: string
  geo_area?: number
  area_unit?: string
  crs_epsg?: number
  active_run_id?: string
  [k: string]: unknown
}

export interface JobStatus {
  job_id: string
  status: "queued" | "running" | "succeeded" | "failed"
  tract_id?: string
  duration_s?: number
  error?: string
  metrics?: Record<string, unknown>
}

export type FeatureCollection = {
  type: "FeatureCollection"
  features: Array<{ type: "Feature"; geometry: unknown; properties: Record<string, unknown> }>
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = (await res.json()) as { detail?: string }
      if (body?.detail) detail = body.detail
    } catch {
      /* 非 JSON 错误体, 保留 statusText */
    }
    throw new Error(`请求失败 (${res.status}): ${detail}`)
  }
  return (await res.json()) as T
}

export async function listTracts(): Promise<Tract[]> {
  return jsonOrThrow(await fetch(`${API_BASE}/tracts`))
}

export async function getObservations(
  tractId: string,
  geometry: "point" | "crown" = "point",
): Promise<FeatureCollection> {
  return jsonOrThrow(
    await fetch(`${API_BASE}/tracts/${encodeURIComponent(tractId)}/observations?geometry=${geometry}`),
  )
}

export async function getJob(jobId: string): Promise<JobStatus> {
  return jsonOrThrow(await fetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}`))
}

// 报告/导出为文件下载, 直接用链接打开。
export function reportUrl(tractId: string, fmt = "pdf"): string {
  return `${API_BASE}/tracts/${encodeURIComponent(tractId)}/report?fmt=${fmt}`
}
export function exportUrl(tractId: string, fmt = "geojson"): string {
  return `${API_BASE}/tracts/${encodeURIComponent(tractId)}/export?fmt=${fmt}`
}
