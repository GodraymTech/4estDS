import type { Permission } from "../../shared/auth";

// 导航项单一真相。与路由对应; 图标名为 AntD 图标组件名(在 NavRail 映射)。
export interface NavItem {
  key: string;
  path: string;
  label: string;
  icon: string;
  perm: Permission;
}

// 主导航(上部)。按业务优先级排序。
export const primaryNav: NavItem[] = [
  {
    key: "map",
    path: "/map",
    label: "一张图",
    icon: "GlobalOutlined",
    perm: "view:overview",
  },
  {
    key: "dashboard",
    path: "/dashboard",
    label: "数据看板",
    icon: "DashboardOutlined",
    perm: "view:dashboard",
  },
  {
    key: "change",
    path: "/change",
    label: "时相对比",
    icon: "SwapOutlined",
    perm: "view:overview",
  },
  {
    key: "ledger",
    path: "/ledger",
    label: "台账",
    icon: "TableOutlined",
    perm: "view:ledger",
  },
  {
    key: "tasks",
    path: "/tasks",
    label: "任务中心",
    icon: "ThunderboltOutlined",
    perm: "run:infer",
  },
  {
    key: "reports",
    path: "/reports",
    label: "报告中心",
    icon: "FileTextOutlined",
    perm: "view:reports",
  },
  {
    key: "alerts",
    path: "/alerts",
    label: "预警中心",
    icon: "AlertOutlined",
    perm: "view:alerts",
  },
  {
    key: "invasion",
    path: "/invasion",
    label: "入侵监测",
    icon: "RadarChartOutlined",
    perm: "view:invasion",
  },
  {
    key: "carbon",
    path: "/carbon",
    label: "蓝碳/MRV",
    icon: "CloudOutlined",
    perm: "view:carbon",
  },
];
