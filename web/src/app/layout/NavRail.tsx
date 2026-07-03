import type { CSSProperties } from "react";
import { NavLink } from "react-router-dom";
import { Tooltip } from "antd";
import {
  AlertOutlined,
  CloudOutlined,
  EnvironmentOutlined,
  FileTextOutlined,
  GlobalOutlined,
  SwapOutlined,
  TableOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import type { ComponentType } from "react";
import { Brand } from "./Brand";
import { primaryNav } from "./navItems";

// 图标名 → 组件映射(避免在数据里存组件, 保持 navItems 为纯数据)。
const ICONS: Record<string, ComponentType> = {
  GlobalOutlined,
  EnvironmentOutlined,
  SwapOutlined,
  TableOutlined,
  ThunderboltOutlined,
  FileTextOutlined,
  AlertOutlined,
  CloudOutlined,
};

// 左侧固定导航 rail(图标 + 悬停提示)。行业几乎统一, 主导航不藏入抽屉。
export function NavRail() {
  return (
    <nav style={WRAP} aria-label="主导航">
      <Brand collapsed />
      <div style={LIST}>
        {primaryNav.map((item) => {
          const Icon = ICONS[item.icon];
          return (
            <Tooltip key={item.key} title={item.label} placement="right">
              <NavLink
                to={item.path}
                style={({ isActive }) => navLinkStyle(isActive)}
                aria-label={item.label}
              >
                {Icon ? <Icon /> : null}
              </NavLink>
            </Tooltip>
          );
        })}
      </div>
    </nav>
  );
}

function navLinkStyle(isActive: boolean): CSSProperties {
  return {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    height: 44,
    fontSize: 20,
    color: isActive ? "#f7f9f8" : "#9fb7ae",
    background: isActive ? "#0e6e63" : "transparent",
    borderRadius: 8,
    margin: "2px 10px",
    transition: "background 0.15s, color 0.15s",
  };
}

const WRAP: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  height: "100%",
};
const LIST: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  marginTop: 8,
};
