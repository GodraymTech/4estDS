import { useEffect } from "react";
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
  const { pathname } = useLocation();

  // 每页同步文档标题: 屏读朗读与浏览器标签页可辨识。
  useEffect(() => {
    const label = titleForPath(pathname);
    document.title = label ? `${label} · 4estDS` : "4estDS 红树林生态监测";
  }, [pathname]);

  return (
    <Layout style={SHELL}>
      <a className="skip-link" href="#main-content">
        跳到主内容
      </a>
      <Sider width={72} collapsedWidth={72} style={SIDER} theme="dark">
        <NavRail />
      </Sider>
      <Layout>
        <Header style={HEADER}>
          <HeaderBar />
        </Header>
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
