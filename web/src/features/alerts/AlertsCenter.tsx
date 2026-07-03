import { useCallback, useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { Alert, Card, Empty, List, Space, Spin, Tag, Typography } from "antd";
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
} from "./alerts";

const { Text } = Typography;

interface ProbeOut {
  items: AlertItem[];
  ready: boolean;
}

// 预警中心: 对每个多时相地点挂探针算变化信号, 汇总定级排序列表。
// 全客户端派生(无新后端依赖); 违法占用/入侵种需权属叠加与分类器, 列为 P3。
export function AlertsCenter({ groups }: { groups: LocationGroup[] }) {
  const multi = useMemo(
    () => groups.filter((g) => g.phases.length >= 2),
    [groups],
  );
  const [byLoc, setByLoc] = useState<Record<string, ProbeOut>>({});

  const report = useCallback((loc: string, out: ProbeOut) => {
    setByLoc((prev) => ({ ...prev, [loc]: out }));
  }, []);

  const all = useMemo(() => {
    const merged = Object.values(byLoc).flatMap((o) => o.items);
    return sortAlerts(merged);
  }, [byLoc]);

  const pending = multi.some((g) => !byLoc[g.location]?.ready);
  const counts = useMemo(() => {
    const c = { high: 0, medium: 0, low: 0 };
    for (const a of all) c[a.severity]++;
    return c;
  }, [all]);

  return (
    <div style={WRAP}>
      {multi.map((g) => (
        <LocationAlertProbe key={g.location} group={g} onResult={report} />
      ))}

      <Space size={8} wrap style={SUMMARY}>
        <Tag color="red">高危 {counts.high}</Tag>
        <Tag color="gold">中级 {counts.medium}</Tag>
        <Tag>低级 {counts.low}</Tag>
        {pending ? <Spin size="small" /> : null}
      </Space>

      {all.length === 0 && !pending ? (
        <Card style={CARD}>
          <Empty description="近两期未发现显著退化 / 清除信号" />
        </Card>
      ) : (
        <List
          dataSource={all}
          renderItem={(a) => (
            <List.Item key={a.id} style={ITEM}>
              <List.Item.Meta
                avatar={<span style={dot(a.severity)} />}
                title={
                  <Space size={8}>
                    <span style={TITLE}>{a.title}</span>
                    <Tag color={tagColor(a.severity)}>
                      {severityLabel(a.severity)}危
                    </Tag>
                    <Text type="secondary" style={LOC}>
                      {a.location}
                    </Text>
                  </Space>
                }
                description={
                  <Space size={12} wrap>
                    <span>{a.detail}</span>
                    <Text type="secondary" style={PERIOD}>
                      {a.period}
                    </Text>
                  </Space>
                }
              />
            </List.Item>
          )}
        />
      )}

      <Alert
        style={FOOT}
        type="info"
        showIcon
        message="能力路线"
        description="违法占用需权属 / 红线图层叠加; 互花米草等入侵种需专项分类器 — 均列入 P3。"
      />
    </div>
  );
}

function LocationAlertProbe({
  group,
  onResult,
}: {
  group: LocationGroup;
  onResult: (loc: string, out: ProbeOut) => void;
}) {
  const [ai, bi] = pickLatestTwo(group.phases);
  const before = group.phases[ai];
  const after = group.phases[bi];
  const beforeObs = useObservations(before?.id, "crown");
  const afterObs = useObservations(after?.id, "crown");
  const ready = ai !== bi && !beforeObs.isFetching && !afterObs.isFetching;

  const items = useMemo(() => {
    if (!ready) return [];
    const m = buildChangeMetrics(beforeObs.data, afterObs.data);
    const d = detectPolygonChanges(beforeObs.data, afterObs.data);
    return deriveAlerts({
      location: group.location,
      beforeTime: before?.time ?? "",
      afterTime: after?.time ?? "",
      areaBefore: m.areaBefore,
      areaPct: m.areaPct,
      countPct: m.countPct,
      lostCount: d.lostCount,
      retainedCount: d.retainedCount,
      lostArea: d.lostArea,
    });
  }, [ready, beforeObs.data, afterObs.data, group.location, before, after]);

  useEffect(() => {
    onResult(group.location, { items, ready });
  }, [group.location, items, ready, onResult]);

  return null;
}

function tagColor(sev: AlertItem["severity"]): string {
  return sev === "high" ? "red" : sev === "medium" ? "gold" : "default";
}

function dot(sev: AlertItem["severity"]): CSSProperties {
  return {
    display: "inline-block",
    width: 10,
    height: 10,
    borderRadius: 999,
    marginTop: 6,
    background: severityColor(sev),
  };
}

const WRAP: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 12,
};
const SUMMARY: CSSProperties = { alignItems: "center" };
const CARD: CSSProperties = { boxShadow: "var(--shadow-2)" };
const ITEM: CSSProperties = { padding: "12px 4px" };
const TITLE: CSSProperties = { fontWeight: 600 };
const LOC: CSSProperties = { fontSize: 12 };
const PERIOD: CSSProperties = {
  fontSize: 12,
  fontVariantNumeric: "tabular-nums",
};
const FOOT: CSSProperties = { marginTop: 4 };
