import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { Button, Space, Tooltip, Typography } from "antd";
import {
  CaretRightOutlined,
  PauseOutlined,
  RedoOutlined,
  StepBackwardOutlined,
  StepForwardOutlined,
} from "@ant-design/icons";
import type { Phase } from "../../entities/phase";
import { pickLatestTwo } from "../../entities/phase";
import { phasePositions } from "./phaseTime";

const { Text } = Typography;

const PLAY_INTERVAL_MS = 1400;
const COLOR_BEFORE = "#c9a24b";
const COLOR_AFTER = "#3e8e5a";
const COLOR_IDLE = "#d8e0dd";

const pct = (x: number) => `${Math.max(0, Math.min(1, x)) * 100}%`;

type Role = "before" | "after" | "idle";

// 多时相时间轴: 按真实获取日期布点，选任意两期对比，并可播放时序演变。
// 播放语义: 固定基线(before)，after 指针沿时间轴逐期推进，直观累积“相对基线的变化”。
export function PhaseTimeline({
  phases,
  range,
  onRangeChange,
}: {
  phases: Phase[];
  range: [number, number];
  onRangeChange: (v: [number, number]) => void;
}) {
  const [playing, setPlaying] = useState(false);
  const positions = phasePositions(phases);
  const last = phases.length - 1;

  // 用 ref 读取最新 range，避免 setInterval 闭包读到过期值。
  const rangeRef = useRef(range);
  rangeRef.current = range;

  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      const [lo, hi] = rangeRef.current;
      if (hi >= last) {
        setPlaying(false);
        return;
      }
      onRangeChange([lo, hi + 1]);
    }, PLAY_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [playing, last, onRangeChange]);

  const togglePlay = useCallback(() => {
    setPlaying((p) => {
      if (p) return false;
      // 已到末期时再次播放: 从基线下一期重新开始。
      const [lo, hi] = rangeRef.current;
      if (hi >= last) onRangeChange([lo, Math.min(lo + 1, last)]);
      return true;
    });
  }, [last, onRangeChange]);

  const setNearer = (i: number) => {
    const [lo, hi] = rangeRef.current;
    const pick: [number, number] =
      Math.abs(i - lo) <= Math.abs(i - hi) ? [i, hi] : [lo, i];
    onRangeChange([Math.min(pick[0], pick[1]), Math.max(pick[0], pick[1])]);
  };

  const step = (dir: -1 | 1) => {
    const [lo, hi] = rangeRef.current;
    onRangeChange([lo, Math.min(last, Math.max(lo, hi + dir))]);
  };

  const reset = () => {
    setPlaying(false);
    onRangeChange(pickLatestTwo(phases));
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
        <Space size={4}>
          <Tooltip title="上一期">
            <Button
              size="small"
              type="text"
              icon={<StepBackwardOutlined />}
              onClick={() => step(-1)}
              disabled={playing || hi <= lo}
            />
          </Tooltip>
          <Button
            size="small"
            type="primary"
            shape="circle"
            icon={playing ? <PauseOutlined /> : <CaretRightOutlined />}
            onClick={togglePlay}
          />
          <Tooltip title="下一期">
            <Button
              size="small"
              type="text"
              icon={<StepForwardOutlined />}
              onClick={() => step(1)}
              disabled={playing || hi >= last}
            />
          </Tooltip>
          <Tooltip title="重置为最新两期">
            <Button
              size="small"
              type="text"
              icon={<RedoOutlined />}
              onClick={reset}
            />
          </Tooltip>
        </Space>
        <Text style={RANGE_LABEL}>
          {phases[lo]?.time || "-"} → {phases[hi]?.time || "-"}
        </Text>
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
  const size = active ? 16 : 10;
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
    border: active ? "2px solid #10302b" : "1px solid #b7c4bf",
    cursor: "pointer",
    padding: 0,
    zIndex: active ? 3 : 2,
    transition: "width .15s, height .15s, margin .15s",
  };
}

const WRAP: CSSProperties = { padding: "8px 16px 12px" };
const HEAD: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  marginBottom: 12,
};
const RANGE_LABEL: CSSProperties = {
  fontVariantNumeric: "tabular-nums",
  color: "var(--color-text, #10302b)",
  fontSize: 13,
};
const TRACK: CSSProperties = {
  position: "relative",
  height: 24,
  margin: "0 8px",
};
const BASELINE: CSSProperties = {
  position: "absolute",
  top: "50%",
  left: 0,
  right: 0,
  height: 2,
  background: COLOR_IDLE,
  transform: "translateY(-50%)",
};
const SPAN: CSSProperties = {
  position: "absolute",
  top: "50%",
  height: 4,
  background: "rgba(62, 142, 90, 0.35)",
  transform: "translateY(-50%)",
  borderRadius: 2,
};
