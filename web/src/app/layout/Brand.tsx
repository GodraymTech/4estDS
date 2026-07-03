import type { CSSProperties } from "react";

// 产品铭牌(标志 + 名称)。标志为内联 SVG: 一滴潮水与树冠(潮间带意象)。
export function BrandMark({ size = 28 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      role="img"
      aria-label="4estDS"
    >
      <path
        d="M16 3 C10 11 6 15 6 21 a10 10 0 0 0 20 0 C26 15 22 11 16 3 Z"
        fill="#0e6e63"
      />
      <path
        d="M16 12 v12 M16 16 l-4 -3 M16 19 l4 -3"
        stroke="#edf1ef"
        strokeWidth={1.6}
        fill="none"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function Brand({ collapsed = false }: { collapsed?: boolean }) {
  return (
    <div style={WRAP}>
      <BrandMark />
      {collapsed ? null : <span style={NAME}>4estDS</span>}
    </div>
  );
}

const WRAP: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "12px 8px",
  justifyContent: "center",
};
const NAME: CSSProperties = {
  color: "#f7f9f8",
  fontFamily: "var(--font-display)",
  fontWeight: 600,
  fontSize: 16,
  letterSpacing: 0.5,
};
