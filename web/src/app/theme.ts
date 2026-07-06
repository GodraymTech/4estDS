import { theme as antdThemeEngine, type ThemeConfig } from "antd";

/**
 * AntD 5 主题令牌。
 * 从设计令牌(潮间带)映射到 AntD, 实现"换肤"以摆脱默认 AntD 观感(设计技能要求)。
 * 说明: AntD 需 JS 数值, 无法直接读取 CSS 变量, 故此处与 tokens.css 保持同值；
 * tokens.css 仍是视觉真相, 此文件是其在 AntD 侧的映射(开闭原则: 扩展主题只改此处)。
 */
const FONT_FAMILY =
  '"IBM Plex Sans", "Source Han Sans SC", "Noto Sans SC", system-ui, sans-serif';

const LIGHT = {
  primary: "#0e6e63",
  success: "#3e8e5a",
  warning: "#c9a24b",
  error: "#b8472a",
  info: "#1e4e8c",
  text: "#10302b",
  muted: "#5c6b66",
  bg: "#edf1ef",
  surface: "#f7f9f8",
  elevated: "#ffffff",
  border: "#d8e0dd",
  hover: "#eef5f2",
  placeholder: "#7a8a85",
};

const DARK = {
  primary: "#36b7a7",
  success: "#60c47a",
  warning: "#d6b75b",
  error: "#e26d4a",
  info: "#6aa7e8",
  text: "#e6f0ed",
  muted: "#9ab1aa",
  bg: "#0b1412",
  surface: "#13211e",
  elevated: "#182b27",
  border: "#28423b",
  hover: "#1b302b",
  placeholder: "#78918a",
};

export type ThemeMode = "light" | "dark";

export function createAntdTheme(mode: ThemeMode): ThemeConfig {
  const dark = mode === "dark";
  const c = dark ? DARK : LIGHT;
  return {
    algorithm: dark ? antdThemeEngine.darkAlgorithm : antdThemeEngine.defaultAlgorithm,
    token: {
      colorPrimary: c.primary,
      colorSuccess: c.success,
      colorWarning: c.warning,
      colorError: c.error,
      colorInfo: c.info,
      colorTextBase: c.text,
      colorText: c.text,
      colorTextSecondary: c.muted,
      colorTextTertiary: c.muted,
      colorTextPlaceholder: c.placeholder,
      colorBgBase: c.bg,
      colorBgLayout: c.bg,
      colorBgContainer: c.surface,
      colorBgElevated: c.elevated,
      colorBorder: c.border,
      colorBorderSecondary: c.border,
      colorFillTertiary: c.hover,
      colorFillQuaternary: dark ? "#10201d" : "#f1f5f3",
      controlItemBgHover: c.hover,
      controlOutline: dark ? "rgba(54, 183, 167, 0.24)" : "rgba(14, 110, 99, 0.18)",
      borderRadius: 8,
      fontFamily: FONT_FAMILY,
      wireframe: false,
    },
    components: {
      Layout: {
        headerBg: "#10302b",
        headerHeight: 56,
        siderBg: "#10302b",
        bodyBg: c.bg,
      },
      Menu: {
        darkItemBg: "#10302b",
        darkItemSelectedBg: dark ? "#168a7d" : "#0e6e63",
        darkItemHoverBg: dark ? "#36b7a733" : "#0e6e6333",
      },
      Card: {
        borderRadiusLG: 8,
        colorBgContainer: c.surface,
        colorBorderSecondary: c.border,
      },
      Button: {
        primaryShadow: "none",
      },
      Input: {
        colorBgContainer: c.elevated,
        colorText: c.text,
        colorTextPlaceholder: c.placeholder,
        colorBorder: c.border,
      },
      InputNumber: {
        colorBgContainer: c.elevated,
        colorText: c.text,
        colorTextPlaceholder: c.placeholder,
        colorBorder: c.border,
      },
      Select: {
        colorBgContainer: c.elevated,
        colorBgElevated: c.elevated,
        colorText: c.text,
        colorTextPlaceholder: c.placeholder,
        optionSelectedBg: dark ? "#203d37" : "#e6f4f1",
        optionActiveBg: c.hover,
      },
      Table: {
        colorBgContainer: c.surface,
        headerBg: dark ? "#182b27" : "#eef4f1",
        headerColor: c.text,
        rowHoverBg: c.hover,
        borderColor: c.border,
      },
      Dropdown: {
        colorBgElevated: c.elevated,
        colorText: c.text,
      },
      Modal: {
        contentBg: c.surface,
        headerBg: c.surface,
        titleColor: c.text,
      },
      Progress: {
        remainingColor: dark ? "#20332f" : "#e2e9e6",
      },
    },
  };
}

export const antdTheme: ThemeConfig = createAntdTheme("light");
