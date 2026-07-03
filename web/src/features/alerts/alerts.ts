// 预警引擎(纯函数, 仅接数值信号): 从两期变化派生退化/清除/株数骤降信号并定级。
// 不耦合 UI/地图/请求; 阈值集中一处, 便于后续校准。
export type AlertSeverity = "high" | "medium" | "low";
export type AlertKind = "degradation" | "clearing" | "count_drop";

export interface ChangeSignal {
  location: string;
  areaPct: number | null; // 冠幅面积变化百分比
  countPct: number | null; // 株数变化百分比
  lostCount: number; // 消失图斑数
  totalBefore: number; // 旧期图斑总数(算 lostRatio)
}

export interface AlertItem {
  id: string;
  location: string;
  kind: AlertKind;
  severity: AlertSeverity;
  title: string;
  detail: string;
}

const SEV_RANK: Record<AlertSeverity, number> = { high: 0, medium: 1, low: 2 };

const KIND_LABEL: Record<AlertKind, string> = {
  degradation: "冠幅退化",
  clearing: "疑似清除",
  count_drop: "株数骤降",
};

export function deriveAlerts(s: ChangeSignal): AlertItem[] {
  const out: AlertItem[] = [];

  // 退化: 冠幅面积显著下降。
  if (s.areaPct !== null && s.areaPct <= -5) {
    const sev: AlertSeverity =
      s.areaPct <= -15 ? "high" : s.areaPct <= -10 ? "medium" : "low";
    out.push({
      id: s.location + ":degradation",
      location: s.location,
      kind: "degradation",
      severity: sev,
      title: KIND_LABEL.degradation,
      detail: "冠幅面积较上一期下降 " + Math.abs(s.areaPct).toFixed(1) + "%。",
    });
  }

  // 疑似清除: 大量图斑消失且占比可观。
  const lostRatio = s.totalBefore > 0 ? s.lostCount / s.totalBefore : 0;
  if (s.lostCount >= 5 && lostRatio >= 0.1) {
    const sev: AlertSeverity =
      lostRatio >= 0.3 ? "high" : lostRatio >= 0.2 ? "medium" : "low";
    out.push({
      id: s.location + ":clearing",
      location: s.location,
      kind: "clearing",
      severity: sev,
      title: KIND_LABEL.clearing,
      detail:
        "消失图斑 " +
        s.lostCount +
        " 处(占旧期 " +
        (lostRatio * 100).toFixed(0) +
        "%)。",
    });
  }

  // 株数骤降。
  if (s.countPct !== null && s.countPct <= -8) {
    const sev: AlertSeverity =
      s.countPct <= -20 ? "high" : s.countPct <= -12 ? "medium" : "low";
    out.push({
      id: s.location + ":count_drop",
      location: s.location,
      kind: "count_drop",
      severity: sev,
      title: KIND_LABEL.count_drop,
      detail: "冠层株数较上一期下降 " + Math.abs(s.countPct).toFixed(1) + "%。",
    });
  }

  return out;
}

export function sortAlerts(items: AlertItem[]): AlertItem[] {
  return [...items].sort((a, b) => SEV_RANK[a.severity] - SEV_RANK[b.severity]);
}

export function severityColor(sev: AlertSeverity): string {
  if (sev === "high") return "#b8472a";
  if (sev === "medium") return "#c9a24b";
  return "#5c6b66";
}

export function severityLabel(sev: AlertSeverity): string {
  if (sev === "high") return "高";
  if (sev === "medium") return "中";
  return "低";
}
