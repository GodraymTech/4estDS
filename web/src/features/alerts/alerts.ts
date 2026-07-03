// 预警引擎(纯函数): 仅吃数值信号, 不耦合其他 feature。
// 从两期变化(聚合量 + 逐图斑)派生退化/清除/株数骤降信号并定级。
export type AlertSeverity = "high" | "medium" | "low";
export type AlertKind = "degradation" | "clearing" | "count_drop";

export interface AlertItem {
  id: string;
  location: string;
  kind: AlertKind;
  severity: AlertSeverity;
  title: string;
  detail: string;
  period: string;
}

// 一个地点两期对比的变化信号(由探针组装)。
export interface ChangeSignal {
  location: string;
  beforeTime: string;
  afterTime: string;
  areaBefore: number; // m²
  areaPct: number | null;
  countPct: number | null;
  lostCount: number;
  retainedCount: number;
  lostArea: number; // m²
}

const SEVERITY_RANK: Record<AlertSeverity, number> = {
  high: 3,
  medium: 2,
  low: 1,
};

function ha(m2: number): string {
  return (m2 / 10000).toFixed(2);
}

function period(a: string, b: string): string {
  return (a || "?") + " \u2192 " + (b || "?");
}

export function deriveAlerts(s: ChangeSignal): AlertItem[] {
  const items: AlertItem[] = [];
  const p = period(s.beforeTime, s.afterTime);

  // ① 冠幅退化(面积下降)。
  if (s.areaPct !== null && s.areaPct <= -5) {
    const sev: AlertSeverity =
      s.areaPct <= -15 ? "high" : s.areaPct <= -10 ? "medium" : "low";
    items.push({
      id: s.location + ":degradation",
      location: s.location,
      kind: "degradation",
      severity: sev,
      title: "\u51a0\u5e45\u9000\u5316",
      detail:
        "\u6811\u51a0\u603b\u9762\u79ef\u4e0b\u964d " +
        Math.abs(s.areaPct).toFixed(1) +
        "%\uff08\u51cf\u5c11 " +
        ha(s.lostArea) +
        " ha\uff09",
      period: p,
    });
  }

  // ② 图斑清除(消失占比)。
  const denom = s.lostCount + s.retainedCount;
  const lostRatio = denom > 0 ? s.lostCount / denom : 0;
  if (s.lostCount >= 5 && lostRatio >= 0.1) {
    const sev: AlertSeverity =
      lostRatio >= 0.3 ? "high" : lostRatio >= 0.2 ? "medium" : "low";
    items.push({
      id: s.location + ":clearing",
      location: s.location,
      kind: "clearing",
      severity: sev,
      title: "\u56fe\u6591\u6e05\u9664",
      detail:
        "\u6d88\u5931\u6811\u51a0 " +
        s.lostCount +
        " \u682a\uff08\u5360\u6bd4 " +
        (lostRatio * 100).toFixed(0) +
        "%\uff09",
      period: p,
    });
  }

  // ③ 株数骤降。
  if (s.countPct !== null && s.countPct <= -8) {
    const sev: AlertSeverity =
      s.countPct <= -20 ? "high" : s.countPct <= -12 ? "medium" : "low";
    items.push({
      id: s.location + ":count_drop",
      location: s.location,
      kind: "count_drop",
      severity: sev,
      title: "\u682a\u6570\u9aa4\u964d",
      detail:
        "\u51a0\u5c42\u682a\u6570\u4e0b\u964d " +
        Math.abs(s.countPct).toFixed(1) +
        "%",
      period: p,
    });
  }

  return items;
}

// 高危优先, 同级按地点名稳定排序。
export function sortAlerts(items: AlertItem[]): AlertItem[] {
  return [...items].sort((a, b) => {
    const d = SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity];
    return d !== 0 ? d : a.location.localeCompare(b.location);
  });
}

export function severityColor(sev: AlertSeverity): string {
  return sev === "high" ? "#b8472a" : sev === "medium" ? "#c9a24b" : "#5c6b66";
}

export function severityLabel(sev: AlertSeverity): string {
  return sev === "high" ? "\u9ad8" : sev === "medium" ? "\u4e2d" : "\u4f4e";
}
