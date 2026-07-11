import type { Phase } from "../../entities/phase";

// 解析时相时间为 epoch 毫秒; 支持 YYYYmmdd / YYYY-MM-DD / YYYY-MM / YYYY / ISO。
// 不可解析返回 null，由调用方降级为均匀分布。
export function parsePhaseTime(time: string | undefined): number | null {
  if (!time) return null;
  const s = time.trim();
  let m = /^(\d{4})(\d{2})(\d{2})$/.exec(s);
  if (m) return Date.UTC(+m[1], +m[2] - 1, +m[3]);
  m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (m) return Date.UTC(+m[1], +m[2] - 1, +m[3]);
  m = /^(\d{4})-(\d{2})$/.exec(s);
  if (m) return Date.UTC(+m[1], +m[2] - 1, 1);
  m = /^(\d{4})$/.exec(s);
  if (m) return Date.UTC(+m[1], 0, 1);
  const t = Date.parse(s);
  return Number.isNaN(t) ? null : t;
}

// 计算每个时相在时间轴上的相对位置(0..1)。
// 若存在不可解析项或跨度为 0，退化为均匀分布(保证可视)。
export function phasePositions(phases: Phase[]): number[] {
  const n = phases.length;
  if (n <= 1) return phases.map(() => 0);
  return phases.map((_, i) => i / (n - 1));
}
