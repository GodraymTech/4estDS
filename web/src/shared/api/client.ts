import { env } from "../config/env";

/**
 * HTTP 客户端(单一职责): 统一拼接 baseURL、解析 JSON、抛出人话错误。
 * 前端其他部分不直接接触 fetch(DRY/高内聚)。
 */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      /* 非 JSON 错误体, 保留 statusText */
    }
    throw new ApiError(res.status, `请求失败 (${res.status}): ${detail}`);
  }
  return (await res.json()) as T;
}

export async function apiGet<T>(path: string): Promise<T> {
  return parse<T>(await fetch(`${env.apiBase}${path}`));
}

/** 拼接绝对 API URL(用于报告/导出等直接下载链接)。 */
export function apiUrl(path: string): string {
  return `${env.apiBase}${path}`;
}
