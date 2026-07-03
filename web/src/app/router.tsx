import { createBrowserRouter, Navigate } from "react-router-dom";
import { AppShell } from "./layout/AppShell";
import { OverviewPage } from "../pages/OverviewPage";
import { AtlasPage } from "../pages/AtlasPage";
import { ChangePage } from "../pages/ChangePage";
import { LedgerPage } from "../pages/LedgerPage";
import { TasksPage } from "../pages/TasksPage";
import { ReportsPage } from "../pages/ReportsPage";
import { AlertsPage } from "../pages/AlertsPage";
import { CarbonPage } from "../pages/CarbonPage";
import { InvasionPage } from "../pages/InvasionPage";
import { AdminPage } from "../pages/AdminPage";
import { ForbiddenPage } from "../pages/ForbiddenPage";
import { NotFoundPage } from "../pages/NotFoundPage";
import { RoleGate } from "../shared/auth";

// 路由装配(薄): 壳为布局父, 页面为子。每页对应一个业务切片。
export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/overview" replace /> },
      { path: "overview", element: <OverviewPage /> },
      { path: "atlas", element: <AtlasPage /> },
      { path: "atlas/:tractId", element: <AtlasPage /> },
      { path: "change", element: <ChangePage /> },
      { path: "ledger", element: <LedgerPage /> },
      {
        path: "tasks",
        element: (
          <RoleGate perm="run:infer" fallback={<ForbiddenPage />}>
            <TasksPage />
          </RoleGate>
        ),
      },
      { path: "reports", element: <ReportsPage /> },
      { path: "alerts", element: <AlertsPage /> },
      { path: "invasion", element: <InvasionPage /> },
      { path: "carbon", element: <CarbonPage /> },
      {
        path: "admin",
        element: (
          <RoleGate perm="admin:system" fallback={<ForbiddenPage />}>
            <AdminPage />
          </RoleGate>
        ),
      },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
