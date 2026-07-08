import type { Tract } from "../../shared/api";

// 时相: 同一地块、不同 phase_id 的一次观测快照。
export interface Phase {
  id: string;
  label: string;
  time: string;
}

export interface TractPhaseGroup {
  tract_id: string;
  phases: Phase[];
}

// 按地块分组时相; 同一地块多时相即可卷帘对比。
export function groupPhasesByTract(tracts: Tract[]): TractPhaseGroup[] {
  const byTract = new Map<string, Phase[]>();
  for (const t of tracts) {
    const tract_id = t.tract_id;
    const phase_id = t.phase_id || "";
    const phase: Phase = {
      id: String(t.tract_phase_pk || t.tract_id),
      label: tract_id + " · " + (phase_id || "未知时相"),
      time: phase_id,
    };
    const arr = byTract.get(tract_id) ?? [];
    arr.push(phase);
    byTract.set(tract_id, arr);
  }
  const groups: TractPhaseGroup[] = [];
  for (const [tract_id, phases] of byTract) {
    phases.sort((a, b) => a.time.localeCompare(b.time));
    groups.push({ tract_id, phases });
  }
  groups.sort((a, b) => b.phases.length - a.phases.length);
  return groups;
}

// 默认对比最新两个时相。
export function pickLatestTwo(phases: Phase[]): [number, number] {
  if (phases.length < 2) return [0, 0];
  return [phases.length - 2, phases.length - 1];
}
