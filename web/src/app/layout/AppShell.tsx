import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { Layout } from "antd";
import { Outlet, useLocation } from "react-router-dom";
import { NavRail } from "./NavRail";
import { HeaderBar } from "./HeaderBar";
import { primaryNav } from "./navItems";

const { Sider, Header, Content } = Layout;

// 主导航之外的页面标题补充。
const EXTRA_TITLES: Record<string, string> = {
  "/admin": "系统管理",
};

function titleForPath(pathname: string): string {
  const item = primaryNav.find(
    (n) => pathname === n.path || pathname.startsWith(n.path + "/"),
  );
  return item?.label ?? EXTRA_TITLES[pathname] ?? "";
}

// 应用外壳: 左侧固定 rail + 顶栏 + 内容区(路由出口)。
// 页脚由具体非地图页自行引入(地图页全屏, 不放 footer)。
export function AppShell() {
  const { pathname, search } = useLocation();
  const editorMode = (pathname.startsWith("/map") && new URLSearchParams(search).has("effective-area"))
    || /^\/review\/[^/]+/.test(pathname);
  const [railPreview, setRailPreview] = useState(false);

  // 每页同步文档标题: 屏读朗读与浏览器标签页可辨识。
  useEffect(() => {
    const label = titleForPath(pathname);
    document.title = label ? `${label} · 4estDS` : "4estDS 红树林生态监测";
  }, [pathname]);

  useEffect(() => {
    if (!editorMode) setRailPreview(false);
  }, [editorMode]);

  return (
    <Layout style={SHELL}>
      <a className="skip-link" href="#main-content">
        跳到主内容
      </a>
      {editorMode && !railPreview ? (
        <div
          aria-label="悬停展开导航"
          style={RAIL_TRIGGER}
          onMouseEnter={() => setRailPreview(true)}
        />
      ) : null}
      <Sider
        width={editorMode && !railPreview ? 0 : 72}
        collapsedWidth={0}
        style={{ ...SIDER, overflow: "hidden", transition: "width 160ms ease" }}
        theme="dark"
        onMouseLeave={() => {
          if (editorMode) setRailPreview(false);
        }}
      >
        <NavRail />
      </Sider>
      <Layout>
        {!editorMode ? (
          <Header style={HEADER}>
            <HeaderBar />
          </Header>
        ) : null}
        <Content id="main-content" role="main" style={CONTENT}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}

const SHELL: CSSProperties = { height: "100vh" };
const SIDER: CSSProperties = { background: "var(--ink)" };
const HEADER: CSSProperties = { paddingInline: 0 };
const CONTENT: CSSProperties = {
  position: "relative",
  display: "flex",
  flexDirection: "column",
  minHeight: 0,
};
const RAIL_TRIGGER: CSSProperties = {
  position: "fixed",
  inset: "0 auto 0 0",
  width: 8,
  zIndex: 1000,
  background: "transparent",
};
