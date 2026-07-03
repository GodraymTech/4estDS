import type { CSSProperties } from "react";
import { Slider, Typography } from "antd";
import type { Phase } from "../../entities/phase";

const { Text } = Typography;

// 时相选择滑块: 现有时相节点均匀分布, 双把手两头均可滑;
// 两个把手分别代表要对比的旧/新时相。
// 单一时相不渲染滑块(由父级处理); 超过两个默认对比最新两个。
export function PhaseSlider({
  phases,
  value,
  onChange,
}: {
  phases: Phase[];
  value: [number, number];
  onChange: (v: [number, number]) => void;
}) {
  const marks: Record<number, string> = {};
  phases.forEach((p, i) => {
    marks[i] = shortLabel(p);
  });

  const tooltip = {
    formatter: (i?: number) => (typeof i === "number" ? phases[i]?.label : ""),
  };

  return (
    <div style={WRAP}>
      <div style={HEAD}>
        <Text strong>时相对比</Text>
        <Text type="secondary">
          {phases[value[0]]?.time || "-"} → {phases[value[1]]?.time || "-"}
        </Text>
      </div>
      <Slider
        range
        min={0}
        max={phases.length - 1}
        step={1}
        marks={marks}
        value={value}
        tooltip={tooltip}
        onChange={(v) => {
          const arr = v as number[];
          const lo = Math.min(arr[0], arr[1]);
          const hi = Math.max(arr[0], arr[1]);
          onChange([lo, hi]);
        }}
      />
    </div>
  );
}

function shortLabel(p: Phase): string {
  // 优先取时间的年-月(避免刻度拥挤)。
  if (p.time && p.time.length >= 7) return p.time.slice(0, 7);
  return p.time || p.label;
}

const WRAP: CSSProperties = { padding: "4px 12px 0" };
const HEAD: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "baseline",
  gap: 12,
  marginBottom: 2,
};
