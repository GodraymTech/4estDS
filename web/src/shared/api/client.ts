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

export async function apiPostJson<T>(path: string, body: unknown): Promise<T> {
  return parse<T>(
    await fetch(`${env.apiBase}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

/**
 * multipart 上传(带进度)。大 TIFF 上传需确定进度, fetch 不支持上传进度, 故用 XHR。
 * 字段名 "file" 与后端 UploadFile 参数对应。
 */
export function apiUpload<T>(
  path: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${env.apiBase}${path}`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as T);
        } catch {
          reject(new ApiError(xhr.status, "上传响应解析失败"));
        }
        return;
      }
      let detail = xhr.statusText;
      try {
        const b = JSON.parse(xhr.responseText) as { detail?: string };
        if (b?.detail) detail = b.detail;
      } catch {
        /* 保留 statusText */
      }
      reject(new ApiError(xhr.status, `上传失败 (${xhr.status}): ${detail}`));
    };
    xhr.onerror = () => reject(new ApiError(0, "网络错误, 上传中断"));
    const fd = new FormData();
    fd.append("file", file);
    xhr.send(fd);
  });
}

/** 拼接绝对 API URL(用于报告/导出等直接下载链接)。 */
export function apiUrl(path: string): string {
  return `${env.apiBase}${path}`;
}
