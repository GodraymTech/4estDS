import type { PropsWithChildren } from "react";
import { App as AntdApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { antdTheme } from "./theme";
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

// 集中装配全局 Provider: 主题换肤 + 中文本地化 + 服务端状态 + AntD 静态方法上下文。
export function AppProviders({ children }: PropsWithChildren) {
  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider theme={antdTheme} locale={zhCN}>
        <AntdApp>
          <RoleProvider>{children}</RoleProvider>
        </AntdApp>
      </ConfigProvider>
    </QueryClientProvider>
  );
}
