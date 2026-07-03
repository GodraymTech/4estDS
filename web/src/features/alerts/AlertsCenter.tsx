import { useCallback, useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { Alert, Card, Empty, List, Space, Tag } from "antd";
import type { LocationGroup } from "../../entities/phase";
import { pickLatestTwo } from "../../entities/phase";
import { useObservations } from "../../entities/observation";
import { buildChangeMetrics } from "../change-metrics";
import { detectPolygonChanges } from "../change-detect";
import {
  deriveAlerts,
  severityColor,
  severityLabel,
  sortAlerts,
  type AlertItem,
  type AlertSeverity,
} from "./alerts";

// 单地点探针: 拉两期冠层观测 → 量化+逐图斑变化 → 派生预警, 上报给中心。
// 以组件形式并发拉取各地点(React Query 去重), 不阻塞整体渲染。
function LocationAlertProbe({
  group,
  onResult,
}: {
  group: LocationGroup;
  onResult: (location: string, items: AlertItem[]) => void;
}) {
  const [before, after] = pickLatestTwo(group.phases);
  const beforePhase = group.phases[before];
  const afterPhase = group.phases[after];
  const beforeObs = useObservations(beforePhase?.id, "crown");
  const afterObs = useObservations(afterPhase?.id, "crown");

  const items = useMemo(() => {
    const m = buildChangeMetrics(beforeObs.data, afterObs.data);
    const d = detectPolygonChanges(beforeObs.data, afterObs.data);
    return deriveAlerts({
      location: group.location,
      areaPct: m.areaPct,
      countPct: m.countPct,
      lostCount: d.lostCount,
      totalBefore: m.countBefore,
    });
  }, [beforeObs.data, afterObs.data, group.location]);

  const ready = !beforeObs.isFetching && !afterObs.isFetching;
  useEffect(() => {
    if (ready) onResult(group.location, items);
  }, [ready, items, group.location, onResult]);

  return null;
}

function sameIds(a: AlertItem[] | undefined, b: AlertItem[]): boolean {
  if (!a || a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i].id !== b[i].id || a[i].severity !== b[i].severity) return false;
  }
  return true;
}

function sevDot(sev: AlertSeverity): CSSProperties {
  return { ...DOT, background: severityColor(sev) };
}

function sevTagColor(sev: AlertSeverity): string {
  if (sev === "high") return "red";
  if (sev === "medium") return "gold";
  return "default";
}

// 预警中心: 汇总各多时相地点的探针结果, 按严重度排序展示。
export function AlertsCenter({ groups }: { groups: LocationGroup[] }) {
  const multi = useMemo(
    () => groups.filter((g) => g.phases.length > 1),
    [groups],
  );
  const [byLoc, setByLoc] = useState<Record<string, AlertItem[]>>({});

  const onResult = useCallback((location: string, items: AlertItem[]) => {
    setByLoc((prev) => {
      if (sameIds(prev[location], items)) return prev;
      return { ...prev, [location]: items };
    });
  }, []);

  const all = useMemo(() => {
    const merged: AlertItem[] = [];
    for (const loc of Object.keys(byLoc)) merged.push(...byLoc[loc]);
    return sortAlerts(merged);
  }, [byLoc]);

  const counts = useMemo(() => {
    const c = { high: 0, medium: 0, low: 0 };
    for (const a of all) c[a.severity]++;
    return c;
  }, [all]);

  return (
    <div>
      {multi.map((g) => (
        <LocationAlertProbe key={g.location} group={g} onResult={onResult} />
      ))}
      <Space size={8} style={SUMMARY} wrap>
        <Tag color="red">高 {counts.high}</Tag>
        <Tag color="gold">中 {counts.medium}</Tag>
        <Tag>低 {counts.low}</Tag>
        <span style={MUTED}>
          共 {all.length} 条 · 覆盖 {multi.length} 个多时相地点
        </span>
      </Space>
      <Card styles={CARD_STYLES}>
        {all.length === 0 ? (
          <Empty description="暂无预警(或缺少多时相数据)" />
        ) : (
          <List
            dataSource={all}
            renderItem={(a) => (
              <List.Item key={a.id}>
                <List.Item.Meta
                  title={
                    <Space size={8}>
                      <span style={sevDot(a.severity)} />
                      <span>{a.title}</span>
                      <Tag>{a.location}</Tag>
                      <Tag color={sevTagColor(a.severity)}>
                        {severityLabel(a.severity)}
                      </Tag>
                    </Space>
                  }
                  description={a.detail}
                />
              </List.Item>
            )}
          />
        )}
      </Card>
      <Alert
        style={INFO}
        type="info"
        showIcon
        message="更多预警类型规划中"
        description="违法占用(需权属/红线叠加)、互花米草入侵专项分类器等归 P3。当前基于两期变化派生退化/清除/株数骤降信号。"
      />
    </div>
  );
}

const SUMMARY: CSSProperties = { marginBottom: 12 };
const MUTED: CSSProperties = {
  fontSize: 12,
  color: "var(--color-text-muted, #5c6b66)",
};
const DOT: CSSProperties = { width: 10, height: 10, borderRadius: 3 };
const CARD_BODY: CSSProperties = { padding: "4px 12px" };
const CARD_STYLES = { body: CARD_BODY };
const INFO: CSSProperties = { marginTop: 16 };
