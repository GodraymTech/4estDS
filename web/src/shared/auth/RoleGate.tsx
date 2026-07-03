import type { PropsWithChildren, ReactNode } from "react";
import { useRole } from "./RoleContext";
import type { Permission } from "./roles";

interface RoleGateProps {
  perm: Permission;
  fallback?: ReactNode;
}

// 权限门控: 有权限渲染 children, 否则渲染 fallback(默认不渲染)。
// 注意: 仅前端体验层门控, 安全边界在后端。
export function RoleGate({
  perm,
  fallback = null,
  children,
}: PropsWithChildren<RoleGateProps>) {
  const { can } = useRole();
  return <>{can(perm) ? children : fallback}</>;
}
