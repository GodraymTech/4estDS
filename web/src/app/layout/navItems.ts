// 导航项单一真相。与路由对应; 图标名为 AntD 图标组件名(在 NavRail 映射)。
export interface NavItem {
  key: string;
  path: string;
  label: string;
  icon: string;
}

// 主导航(上部)。按业务优先级排序。
export const primaryNav: NavItem[] = [
  { key: "overview", path: "/overview", label: "总览", icon: "GlobalOutlined" },
  {
    key: "atlas",
    path: "/atlas",
    label: "地块工作台",
    icon: "EnvironmentOutlined",
  },
  { key: "change", path: "/change", label: "变化检测", icon: "SwapOutlined" },
  { key: "ledger", path: "/ledger", label: "台账", icon: "TableOutlined" },
  {
    key: "tasks",
    path: "/tasks",
    label: "任务中心",
    icon: "ThunderboltOutlined",
  },
  {
    key: "reports",
    path: "/reports",
    label: "报告中心",
    icon: "FileTextOutlined",
  },
  { key: "alerts", path: "/alerts", label: "预警中心", icon: "AlertOutlined" },
  { key: "carbon", path: "/carbon", label: "蓝碳/MRV", icon: "CloudOutlined" },
];
