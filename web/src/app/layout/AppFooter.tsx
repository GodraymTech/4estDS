import type { CSSProperties } from "react";
import { APP_META } from "../../shared/config/appMeta";

// 页脚: 仅非地图全屏页显示(避免遮挡地图)。放版权/备案/等保/隐私/条款。
export function AppFooter() {
  const year = new Date().getFullYear();
  return (
    <footer style={WRAP}>
      <span>
        © {year} {APP_META.vendor}
      </span>
      <span style={SEP}>·</span>
      <span className="mono">{APP_META.icp}</span>
      <span style={SEP}>·</span>
      <span className="mono">{APP_META.mps}</span>
      <span style={SEP}>·</span>
      <a href="/privacy" style={LINK}>
        隐私策略
      </a>
      <span style={SEP}>·</span>
      <a href="/terms" style={LINK}>
        服务条款
      </a>
    </footer>
  );
}

const WRAP: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: 6,
  padding: "10px 16px",
  fontSize: 12,
  color: "var(--color-text-muted)",
  borderTop: "1px solid var(--color-border)",
  background: "var(--color-surface)",
};
const SEP: CSSProperties = { color: "var(--color-border)" };
const LINK: CSSProperties = { color: "var(--color-text-muted)" };
