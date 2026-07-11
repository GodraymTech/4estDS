import { useRef, useState } from "react";
import type { CSSProperties, PointerEvent as ReactPointerEvent } from "react";
import { Tooltip, Typography } from "antd";
import type { Phase } from "../../entities/phase";
import { phasePositions } from "./phaseTime";

const { Text } = Typography;

const COLOR_BEFORE = "#c9a24b";
const COLOR_AFTER = "#3e8e5a";
const COLOR_IDLE = "var(--glass-muted)";

const pct = (x: number) => `${Math.max(0, Math.min(1, x)) * 100}%`;

type Role = "before" | "after" | "idle";
type HandleRole = Exclude<Role, "idle">;
interface DragState {
  role: HandleRole;
  position: number;
}

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
  const trackRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef<DragState | null>(null);
  const [dragging, setDragging] = useState<DragState | null>(null);
  rangeRef.current = range;

  const setNearer = (i: number) => {
    const [lo, hi] = rangeRef.current;
    const pick: [number, number] =
      Math.abs(i - lo) <= Math.abs(i - hi) ? [i, hi] : [lo, i];
    onRangeChange([Math.min(pick[0], pick[1]), Math.max(pick[0], pick[1])]);
  };

  const [lo, hi] = range;
  const pointerPosition = (clientX: number) => {
    const rect = trackRef.current?.getBoundingClientRect();
    if (!rect || rect.width <= 0) return null;
    return Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
  };
  const nearestPhase = (ratio: number) => {
    return positions.reduce(
      (nearest, position, index) =>
        Math.abs(position - ratio) < Math.abs(positions[nearest] - ratio) ? index : nearest,
      0,
    );
  };
  const onHandleDown = (event: ReactPointerEvent<HTMLButtonElement>, role: HandleRole) => {
    const [currentLo, currentHi] = rangeRef.current;
    const initial: DragState = {
      role,
      position: role === "before" ? positions[currentLo] : positions[currentHi],
    };
    draggingRef.current = initial;
    setDragging(initial);

    const handlePointerMove = (e: PointerEvent) => {
      if (!draggingRef.current) return;
      const position = pointerPosition(e.clientX);
      if (position === null) return;
      const next = { ...draggingRef.current, position };
      draggingRef.current = next;
      setDragging(next);
    };

    const handlePointerUp = () => {
      const activeDrag = draggingRef.current;
      if (activeDrag) {
        const index = nearestPhase(activeDrag.position);
        const [currLo, currHi] = rangeRef.current;
        const maxIdx = phases.length - 1;
        let next: [number, number] = [currLo, currHi];

        if (activeDrag.role === "before") {
          if (index < currHi) {
            next = [index, currHi];
          } else if (index === currHi) {
            if (currHi < maxIdx) {
              next = [index, currHi + 1];
            } else {
              next = [currHi - 1, currHi];
            }
          } else {
            // index > currHi (跨越)
            next = [currHi, index];
          }
        } else {
          // role === "after"
          if (index > currLo) {
            next = [currLo, index];
          } else if (index === currLo) {
            if (currLo > 0) {
              next = [currLo - 1, index];
            } else {
              next = [currLo, currLo + 1];
            }
          } else {
            // index < currLo (跨越)
            next = [index, currLo];
          }
        }

        // 最终修正以保证 [lo, hi] 顺序且不重合
        let finalLo = Math.min(next[0], next[1]);
        let finalHi = Math.max(next[0], next[1]);
        if (finalLo === finalHi) {
          if (finalLo > 0) {
            finalLo -= 1;
          } else if (finalHi < maxIdx) {
            finalHi += 1;
          }
        }
        if (finalLo !== currLo || finalHi !== currHi) {
          onRangeChange([finalLo, finalHi]);
        }
      }
      draggingRef.current = null;
      setDragging(null);
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
    };

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    event.preventDefault();
  };
  const beforePosition = dragging?.role === "before" ? dragging.position : positions[lo];
  const afterPosition = dragging?.role === "after" ? dragging.position : positions[hi];
  const spanStyle: CSSProperties = {
    ...SPAN,
    left: pct(beforePosition),
    width: pct(afterPosition - beforePosition),
  };

  return (
    <div style={WRAP}>
      <div style={HEAD}>
        <Text style={RANGE_LABEL}>{phases[lo]?.time || "-"}</Text>
        <Text style={RANGE_LABEL}>{phases[hi]?.time || "-"}</Text>
      </div>

      <div ref={trackRef} style={TRACK}>
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
                onClick={() => {
                  if (!active) setNearer(i);
                }}
                onPointerDown={role === "idle" ? undefined : (event) => onHandleDown(event, role)}
                style={nodeStyle(i === lo ? beforePosition : i === hi ? afterPosition : positions[i], role, active)}
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
  const size = active ? 16 : 9;
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
    touchAction: "none",
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
  height: 30,
  margin: "0 5px",
};
const BASELINE: CSSProperties = {
  position: "absolute",
  top: "50%",
  left: 0,
  right: 0,
  height: 6,
  background: "var(--glass-border)",
  transform: "translateY(-50%)",
  borderRadius: 3,
};
const SPAN: CSSProperties = {
  position: "absolute",
  top: "50%",
  height: 8,
  background: "color-mix(in srgb, var(--glass-text) 28%, transparent)",
  transform: "translateY(-50%)",
  borderRadius: 4,
};
