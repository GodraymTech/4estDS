import type { CSSProperties, ReactNode } from "react";

export function MapGlassPanel({
  title,
  style,
  children,
}: {
  title?: ReactNode;
  style?: CSSProperties;
  children: ReactNode;
}) {
  return (
    <section style={{ ...PANEL, ...style }}>
      {title ? <div style={TITLE}>{title}</div> : null}
      <div style={BODY}>{children}</div>
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
