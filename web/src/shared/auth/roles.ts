// 角色与权限单一真相 (前端 RBAC 壳)。
// 说明: 前端门控仅为体验/最小暴露; 真正的安全边界在后端(RLS + 鉴权)。
export type Role = "admin" | "regulator" | "analyst" | "viewer";

export type Permission =
  | "view:overview"
  | "view:atlas"
  | "view:change"
  | "view:ledger"
  | "view:reports"
  | "view:alerts"
  | "view:carbon"
  | "view:invasion"
  | "run:infer"
  | "manage:reports"
  | "admin:system";

export const ALL_PERMISSIONS: Permission[] = [
  "view:overview",
  "view:atlas",
  "view:change",
  "view:ledger",
  "view:reports",
  "view:alerts",
  "view:carbon",
  "view:invasion",
  "run:infer",
  "manage:reports",
  "admin:system",
];

export interface RoleMeta {
  label: string;
  desc: string;
}

export const ROLES: Role[] = ["admin", "regulator", "analyst", "viewer"];

export const ROLE_META: Record<Role, RoleMeta> = {
  admin: { label: "系统管理员", desc: "全部权限: 用户/角色/租户与系统参数。" },
  regulator: {
    label: "监管员",
    desc: "监管视角: 查看、预警、台账与报告审批/导出。",
  },
  analyst: {
    label: "分析员",
    desc: "作业视角: 发起推理、变化分析与报告产出。",
  },
  viewer: { label: "访客", desc: "只读: 总览与各业务视图。" },
};

// 各视图的只读权限(四角色均具备)。
const VIEW_ALL: Permission[] = [
  "view:overview",
  "view:atlas",
  "view:change",
  "view:ledger",
  "view:reports",
  "view:alerts",
  "view:carbon",
  "view:invasion",
];

export const ROLE_PERMISSIONS: Record<Role, Permission[]> = {
  admin: ALL_PERMISSIONS,
  regulator: [...VIEW_ALL, "manage:reports"],
  analyst: [...VIEW_ALL, "run:infer", "manage:reports"],
  viewer: [...VIEW_ALL],
};

export const DEFAULT_ROLE: Role = "admin";

export function isRole(value: unknown): value is Role {
  return typeof value === "string" && (ROLES as string[]).includes(value);
}

export function hasPermission(role: Role, perm: Permission): boolean {
  return ROLE_PERMISSIONS[role].includes(perm);
}

export function permissionsOf(role: Role): Permission[] {
  return ROLE_PERMISSIONS[role];
}
