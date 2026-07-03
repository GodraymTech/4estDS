import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";
import type { PropsWithChildren } from "react";
import { hasPermission, type Permission, type Role } from "./roles";
import {
  persistRole,
  persistTenant,
  readStoredRole,
  readStoredTenant,
} from "./session";

interface RoleContextValue {
  role: Role;
  tenant: string;
  setRole: (role: Role) => void;
  setTenant: (tenant: string) => void;
  can: (perm: Permission) => boolean;
}

const RoleContext = createContext<RoleContextValue | null>(null);

// 当前会话(角色 + 租户)上下文。初值从 localStorage 恢复, 变更同步回写。
export function RoleProvider({ children }: PropsWithChildren) {
  const [role, setRoleState] = useState<Role>(() => readStoredRole());
  const [tenant, setTenantState] = useState<string>(() => readStoredTenant());

  const setRole = useCallback((next: Role) => {
    persistRole(next);
    setRoleState(next);
  }, []);

  const setTenant = useCallback((next: string) => {
    persistTenant(next);
    setTenantState(next);
  }, []);

  const value = useMemo<RoleContextValue>(
    () => ({
      role,
      tenant,
      setRole,
      setTenant,
      can: (perm) => hasPermission(role, perm),
    }),
    [role, tenant, setRole, setTenant],
  );

  return <RoleContext.Provider value={value}>{children}</RoleContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useRole(): RoleContextValue {
  const ctx = useContext(RoleContext);
  if (!ctx) throw new Error("useRole 必须在 RoleProvider 内使用");
  return ctx;
}
