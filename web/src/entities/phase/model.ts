import type { Tract } from "../../shared/api";

// 时相: 同一地点、不同获取时间的一次观测快照。
// (P1: 由 tract.acquisition_time 派生; P2 接入后端多时相栓格影像时间序列端点。)
export interface Phase {
  id: string;
  label: string;
  time: string;
}

export interface LocationGroup {
  location: string;
  phases: Phase[];
}

// 按地点分组地块, 将各获取时间视为一个时相; 同地点多时相即可卷帘对比。
export function groupPhasesByLocation(tracts: Tract[]): LocationGroup[] {
  const byLoc = new Map<string, Phase[]>();
  for (const t of tracts) {
    const loc = t.location || t.name || t.tract_id;
    const time = t.acquisition_time || "";
    const phase: Phase = {
      id: t.tract_id,
      label: loc + " \u00b7 " + (time || "\u672a\u77e5\u65f6\u76f8"),
      time,
    };
    const arr = byLoc.get(loc) ?? [];
    arr.push(phase);
    byLoc.set(loc, arr);
  }
  const groups: LocationGroup[] = [];
  for (const [location, phases] of byLoc) {
    phases.sort((a, b) => a.time.localeCompare(b.time));
    groups.push({ location, phases });
  }
  // 多时相地点优先展示。
  groups.sort((a, b) => b.phases.length - a.phases.length);
  return groups;
}

// 默认对比最新两个时相。
export function pickLatestTwo(phases: Phase[]): [number, number] {
  if (phases.length < 2) return [0, 0];
  return [phases.length - 2, phases.length - 1];
}
