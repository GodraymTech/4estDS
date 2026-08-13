import type { CSSProperties, ReactNode } from "react";

export interface MapGlassPanelProps {
  title?: ReactNode;
  style?: CSSProperties;
  bodyStyle?: CSSProperties;
  /** 背景不透明度 (0 ~ 1) */
  glassOpacity?: number;
  /** 毛玻璃模糊度 (如 8, 16 或 '12px') */
  blur?: number | string;
  children: ReactNode;
}

export function MapGlassPanel({
  title,
  style,
  bodyStyle,
  glassOpacity,
  blur,
  children,
}: MapGlassPanelProps) {
  const panelStyle: CSSProperties = {
    ...PANEL,
    ...(glassOpacity != null
      ? { background: `color-mix(in srgb, var(--glass-bg) ${Math.round(glassOpacity * 100)}%, transparent)` }
      : {}),
    ...(blur != null
      ? {
          backdropFilter: `blur(${typeof blur === "number" ? `${blur}px` : blur}) saturate(160%)`,
          WebkitBackdropFilter: `blur(${typeof blur === "number" ? `${blur}px` : blur}) saturate(160%)`,
        }
      : {}),
    ...style,
  };
  return (
    <section style={panelStyle}>
      {title ? <div style={TITLE}>{title}</div> : null}
      <div style={{ ...BODY, ...bodyStyle }}>{children}</div>
    </section>
  );
}

const PANEL: CSSProperties = {
  border: "1px solid var(--glass-border)",
  borderRadius: 8,
  background: "var(--glass-bg)",
  boxShadow: "var(--glass-shadow), var(--glass-inner)",
  backdropFilter: "blur(16px) saturate(150%)",
  color: "var(--glass-text)",
};
const TITLE: CSSProperties = {
  padding: "10px 12px 8px",
  borderBottom: "1px solid var(--glass-border)",
  fontSize: 14,
  fontWeight: 600,
  lineHeight: 1.25,
};
const BODY: CSSProperties = { padding: 12 };
