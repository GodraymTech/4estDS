import type { ThemeConfig } from "antd";

/**
 * AntD 5 主题令牌。
 * 从设计令牌(潮间带)映射到 AntD, 实现"换肤"以摆脱默认 AntD 观感(设计技能要求)。
 * 说明: AntD 需 JS 数值, 无法直接读取 CSS 变量, 故此处与 tokens.css 保持同值;
 * tokens.css 仍是视觉真相, 此文件是其在 AntD 侧的映射(开闭原则: 扩展主题只改此处)。
 */
export const antdTheme: ThemeConfig = {
  token: {
    colorPrimary: "#0e6e63",
    colorSuccess: "#3e8e5a",
    colorWarning: "#c9a24b",
    colorError: "#b8472a",
    colorInfo: "#1e4e8c",
    colorTextBase: "#10302b",
    colorBgBase: "#f7f9f8",
    colorBgLayout: "#edf1ef",
    colorBorder: "#d8e0dd",
    borderRadius: 8,
    fontFamily:
      '"IBM Plex Sans", "Source Han Sans SC", "Noto Sans SC", system-ui, sans-serif',
    wireframe: false,
  },
  components: {
    Layout: {
      headerBg: "#10302b",
      headerHeight: 56,
      siderBg: "#10302b",
      bodyBg: "#edf1ef",
    },
    Menu: {
      darkItemBg: "#10302b",
      darkItemSelectedBg: "#0e6e63",
      darkItemHoverBg: "#0e6e6333",
    },
    Card: {
      borderRadiusLG: 12,
    },
    Button: {
      primaryShadow: "none",
    },
  },
};
