import type { CSSProperties } from "react";
import { Layout } from "antd";
import { Outlet } from "react-router-dom";
import { NavRail } from "./NavRail";
import { HeaderBar } from "./HeaderBar";

const { Sider, Header, Content } = Layout;

// 应用外壳: 左侧固定 rail + 顶栏 + 内容区(路由出口)。
// 页脚由具体非地图页自行引入(地图页全屏, 不放 footer)。
export function AppShell() {
  return (
    <Layout style={SHELL}>
      <Sider width={72} collapsedWidth={72} style={SIDER} theme="dark">
        <NavRail />
      </Sider>
      <Layout>
        <Header style={HEADER}>
          <HeaderBar />
        </Header>
        <Content style={CONTENT}>
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
