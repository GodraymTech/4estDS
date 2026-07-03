// 会话持久化(角色 + 租户): localStorage 为单一真相, 供 Context 与 HTTP 客户端共享。
// HTTP 客户端为纯函数, 无法读 React Context, 故通过本模块桥接。
import { DEFAULT_ROLE, isRole, type Role } from "./roles";

const ROLE_KEY = "forestds.role";
const TENANT_KEY = "forestds.tenant";
export const DEFAULT_TENANT = "default";

function safeLocal(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null; // 隐私模式/受限环境下降级为无持久化。
  }
}

export function readStoredRole(): Role {
  const raw = safeLocal()?.getItem(ROLE_KEY);
  return isRole(raw) ? raw : DEFAULT_ROLE;
}

export function readStoredTenant(): string {
  return safeLocal()?.getItem(TENANT_KEY) || DEFAULT_TENANT;
}

export function persistRole(role: Role): void {
  safeLocal()?.setItem(ROLE_KEY, role);
}

export function persistTenant(tenant: string): void {
  safeLocal()?.setItem(TENANT_KEY, tenant || DEFAULT_TENANT);
}

// 供 HTTP 客户端注入: 租户 → RLS(X-Tenant-Id), 角色 → 审计/后端二次校验(X-Role)。
export function authHeaders(): Record<string, string> {
  return {
    "X-Tenant-Id": readStoredTenant(),
    "X-Role": readStoredRole(),
  };
}
