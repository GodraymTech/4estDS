import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { PropsWithChildren } from "react";
import { App as AntdApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createAntdTheme, type ThemeMode } from "./theme";
import { RoleProvider } from "../shared/auth";

// 服务端状态客户端: 全局单例, 集中默认策略(缓存/重试)。
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 180_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

interface ThemeContextValue {
  mode: ThemeMode;
  dark: boolean;
  setMode: (mode: ThemeMode) => void;
  toggleMode: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function initialThemeMode(): ThemeMode {
  const stored = localStorage.getItem("forestds-theme");
  return stored === "dark" ? "dark" : "light";
}

// 集中装配全局 Provider: 主题换肤 + 中文本地化 + 服务端状态 + AntD 静态方法上下文。
export function AppProviders({ children }: PropsWithChildren) {
  const [mode, setMode] = useState<ThemeMode>(initialThemeMode);
  const theme = useMemo(() => createAntdTheme(mode), [mode]);
  const themeValue = useMemo<ThemeContextValue>(
    () => ({
      mode,
      dark: mode === "dark",
      setMode,
      toggleMode: () => setMode((v) => (v === "dark" ? "light" : "dark")),
    }),
    [mode],
  );

  useEffect(() => {
    document.documentElement.dataset.theme = mode;
    localStorage.setItem("forestds-theme", mode);
  }, [mode]);

  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider theme={theme} locale={zhCN}>
        <ThemeContext.Provider value={themeValue}>
          <AntdApp>
            <RoleProvider>{children}</RoleProvider>
          </AntdApp>
        </ThemeContext.Provider>
      </ConfigProvider>
    </QueryClientProvider>
  );
}

export function useAppTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useAppTheme must be used inside AppProviders");
  return ctx;
}
