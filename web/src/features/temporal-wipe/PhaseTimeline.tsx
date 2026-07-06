import { useRef } from "react";
import type { CSSProperties } from "react";
import { Tooltip, Typography } from "antd";
import type { Phase } from "../../entities/phase";
import { phasePositions } from "./phaseTime";

const { Text } = Typography;

const COLOR_BEFORE = "#c9a24b";
const COLOR_AFTER = "#3e8e5a";
const COLOR_IDLE = "var(--glass-muted)";

const pct = (x: number) => `${Math.max(0, Math.min(1, x)) * 100}%`;

type Role = "before" | "after" | "idle";

// 紧凑时相轴: 只做两期选择，不做播放器式控件。
export function PhaseTimeline({
  phases,
  range,
  onRangeChange,
}: {
  phases: Phase[];
  range: [number, number];
  onRangeChange: (v: [number, number]) => void;
}) {
  const positions = phasePositions(phases);
  const rangeRef = useRef(range);
  rangeRef.current = range;

  const setNearer = (i: number) => {
    const [lo, hi] = rangeRef.current;
    const pick: [number, number] =
      Math.abs(i - lo) <= Math.abs(i - hi) ? [i, hi] : [lo, i];
    onRangeChange([Math.min(pick[0], pick[1]), Math.max(pick[0], pick[1])]);
  };

  const [lo, hi] = range;
  const spanStyle: CSSProperties = {
    ...SPAN,
    left: pct(positions[lo]),
    width: pct(positions[hi] - positions[lo]),
  };

  return (
    <div style={WRAP}>
      <div style={HEAD}>
        <Text style={RANGE_LABEL}>{phases[lo]?.time || "-"}</Text>
        <Text style={RANGE_LABEL}>{phases[hi]?.time || "-"}</Text>
      </div>

      <div style={TRACK}>
        <div style={BASELINE} />
        <div style={spanStyle} />
        {phases.map((p, i) => {
          const role: Role = i === lo ? "before" : i === hi ? "after" : "idle";
          const active = i === lo || i === hi;
          return (
            <Tooltip title={p.label} key={p.id}>
              <button
                type="button"
                aria-label={p.label}
                onClick={() => setNearer(i)}
                style={nodeStyle(positions[i], role, active)}
              />
            </Tooltip>
          );
        })}
      </div>
    </div>
  );
}

function nodeStyle(pos: number, role: Role, active: boolean): CSSProperties {
  const color =
    role === "before"
      ? COLOR_BEFORE
      : role === "after"
        ? COLOR_AFTER
        : COLOR_IDLE;
  const size = active ? 12 : 7;
  return {
    position: "absolute",
    left: pct(pos),
    top: "50%",
    width: size,
    height: size,
    marginLeft: -(size / 2),
    marginTop: -(size / 2),
    borderRadius: "50%",
    background: color,
    border: active ? "1px solid var(--glass-text)" : "1px solid var(--glass-border)",
    cursor: "pointer",
    padding: 0,
    zIndex: active ? 3 : 2,
    transition: "width .15s, height .15s, margin .15s",
  };
}

const WRAP: CSSProperties = { padding: "6px 10px 8px" };
const HEAD: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  marginBottom: 4,
};
const RANGE_LABEL: CSSProperties = {
  fontVariantNumeric: "tabular-nums",
  color: "var(--glass-text)",
  fontSize: 12,
};
const TRACK: CSSProperties = {
  position: "relative",
  height: 18,
  margin: "0 5px",
};
const BASELINE: CSSProperties = {
  position: "absolute",
  top: "50%",
  left: 0,
  right: 0,
  height: 2,
  background: "var(--glass-border)",
  transform: "translateY(-50%)",
};
const SPAN: CSSProperties = {
  position: "absolute",
  top: "50%",
  height: 3,
  background: "color-mix(in srgb, var(--glass-text) 28%, transparent)",
  transform: "translateY(-50%)",
  borderRadius: 2,
};
