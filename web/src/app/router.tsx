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
import { AdminPage } from "../pages/AdminPage";
import { NotFoundPage } from "../pages/NotFoundPage";

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
      { path: "tasks", element: <TasksPage /> },
      { path: "reports", element: <ReportsPage /> },
      { path: "alerts", element: <AlertsPage /> },
      { path: "carbon", element: <CarbonPage /> },
      { path: "admin", element: <AdminPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
