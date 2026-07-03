import { RouterProvider } from "react-router-dom";
import { AppProviders } from "./providers";
import { ErrorBoundary } from "./ErrorBoundary";
import { router } from "./router";

// 应用根: 错误边界 → 全局 Provider → 路由。保持极薄。
export default function App() {
  return (
    <ErrorBoundary>
      <AppProviders>
        <RouterProvider router={router} />
      </AppProviders>
    </ErrorBoundary>
  );
}
