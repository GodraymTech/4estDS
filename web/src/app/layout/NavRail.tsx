import type { CSSProperties } from "react";
import { NavLink } from "react-router-dom";
import { Tooltip } from "antd";
import {
  AlertOutlined,
  CloudOutlined,
  DashboardOutlined,
  FileTextOutlined,
  GlobalOutlined,
  TableOutlined,
  RadarChartOutlined,
  SwapOutlined,
  ThunderboltOutlined,
  AuditOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from "@ant-design/icons";
import type { ComponentType } from "react";
import { Brand } from "./Brand";
import { primaryNav } from "./navItems";
import { useRole } from "../../shared/auth";

// 图标名 → 组件映射(避免在数据里存组件, 保持 navItems 为纯数据)。
const ICONS: Record<string, ComponentType> = {
  GlobalOutlined,
  DashboardOutlined,
  SwapOutlined,
  TableOutlined,
  ThunderboltOutlined,
  FileTextOutlined,
  AlertOutlined,
  RadarChartOutlined,
  CloudOutlined,
  AuditOutlined,
};

export interface NavRailProps {
  expanded?: boolean;
  onToggleExpand?: () => void;
}

// 左侧固定导航 rail(图标 + 悬停提示 / 展开后图标+文字)。行业规范，支持类似 Chrome 垂直标签页的收起/展开。
export function NavRail({ expanded = false, onToggleExpand }: NavRailProps) {
  const { can } = useRole();
  return (
    <nav style={WRAP} aria-label="主导航">
      <Brand collapsed={!expanded} />
      <div style={LIST}>
        {primaryNav
          .filter((item) => can(item.perm))
          .map((item) => {
            const Icon = ICONS[item.icon];
            const isMap = item.path === "/map";
            return (
              <Tooltip
                key={item.key}
                title={expanded ? "" : item.label}
                placement="right"
              >
                <NavLink
                  to={item.path}
                  state={isMap ? { resetOverview: Date.now() } : undefined}
                  onClick={isMap ? () => window.dispatchEvent(new CustomEvent("4estds:return-overview")) : undefined}
                  style={({ isActive }) => navLinkStyle(isActive, expanded)}
                  aria-label={item.label}
                >
                  {Icon ? <Icon /> : null}
                  {expanded ? (
                    <span style={LABEL_TEXT}>{item.label}</span>
                  ) : null}
                </NavLink>
              </Tooltip>
            );
          })}
      </div>
      <div style={FOOTER}>
        <Tooltip
          title={expanded ? "" : "展开"}
          placement="right"
        >
          <button
            type="button"
            onClick={onToggleExpand}
            style={toggleButtonStyle(expanded)}
            aria-label={expanded ? "收起导航" : "展开导航"}
          >
            {expanded ? <MenuFoldOutlined /> : <MenuUnfoldOutlined />}
            {expanded ? <span style={TOGGLE_LABEL}>收起</span> : null}
          </button>
        </Tooltip>
      </div>
    </nav>
  );
}

function navLinkStyle(isActive: boolean, expanded: boolean): CSSProperties {
  return {
    display: "flex",
    alignItems: "center",
    justifyContent: expanded ? "flex-start" : "center",
    height: 42,
    fontSize: 18,
    color: isActive ? "#f7f9f8" : "#9fb7ae",
    background: isActive ? "#0e6e63" : "transparent",
    borderRadius: 8,
    margin: "2px 8px",
    padding: expanded ? "0 12px" : "0",
    gap: expanded ? 10 : 0,
    textDecoration: "none",
    transition: "background 0.15s, color 0.15s, padding 0.15s",
    overflow: "hidden",
    whiteSpace: "nowrap",
  };
}

function toggleButtonStyle(expanded: boolean): CSSProperties {
  return {
    display: "flex",
    alignItems: "center",
    justifyContent: expanded ? "flex-start" : "center",
    width: "100%",
    height: 40,
    fontSize: 18,
    color: "#9fb7ae",
    background: "transparent",
    border: "none",
    borderRadius: 8,
    cursor: "pointer",
    padding: expanded ? "0 12px" : "0",
    gap: expanded ? 10 : 0,
    transition: "background 0.15s, color 0.15s",
    overflow: "hidden",
    whiteSpace: "nowrap",
  };
}

const LABEL_TEXT: CSSProperties = {
  fontSize: 14,
  fontWeight: 500,
  whiteSpace: "nowrap",
};

const TOGGLE_LABEL: CSSProperties = {
  fontSize: 13,
  whiteSpace: "nowrap",
};

const FOOTER: CSSProperties = {
  marginTop: "auto",
  padding: "8px",
  borderTop: "1px solid rgba(255, 255, 255, 0.08)",
};

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
