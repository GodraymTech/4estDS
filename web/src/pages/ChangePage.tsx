import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { Card, Empty, Select, Space, Spin, Typography } from "antd";
import { useSearchParams } from "react-router-dom";
import { useTracts, type Tract } from "../entities/tract";
import { pickLatestTwo, type Phase } from "../entities/phase";
import { ChangeMetricsPanel } from "../features/change-metrics";
import { TemporalCompare } from "../features/temporal-wipe";
import { tractCenter } from "../features/overview/tractGeo";
import { env } from "../shared/config/env";
import {
  ROAD_OVERLAY,
  basemapById,
  type LngLat,
} from "../shared/map-core";
import { MapFloatingToolbar } from "../shared/ui/MapFloatingToolbar";
import type { TemporalWipeApi } from "../shared/ui/TemporalWipe";

const { Text } = Typography;

interface CompareGroup {
  tract_id: string;
  phases: Phase[];
  center: LngLat;
}

export function ChangePage() {
  const { data: tracts, isLoading } = useTracts();
  const [params, setParams] = useSearchParams();
  const requestedTractId = params.get("tract_id") ?? undefined;
  const groups = useMemo(() => buildCompareGroups(tracts ?? []), [tracts]);
  const [tractId, setTractId] = useState<string | undefined>(undefined);
  const [basemapId, setBasemapId] = useState(env.defaultBasemapId);
  const [roadVisible, setRoadVisible] = useState(true);
  const [wipeApi, setWipeApi] = useState<TemporalWipeApi | null>(null);

  const active = useMemo(() => {
    if (groups.length === 0) return undefined;
    return (
      groups.find((g) => g.tract_id === tractId)
      ?? groups.find((g) => g.tract_id === requestedTractId)
      ?? groups[0]
    );
  }, [groups, tractId, requestedTractId]);

  const [range, setRange] = useState<[number, number]>([0, 0]);
  const roadOverlay = roadVisible
    ? { ...ROAD_OVERLAY, opacity: basemapId === "satellite" ? 0.52 : 0.24 }
    : null;

  useEffect(() => {
    if (active) setRange(pickLatestTwo(active.phases));
  }, [active]);

  const options = groups.map((g) => ({
    value: g.tract_id,
    label: g.tract_id + "（" + g.phases.length + " 时相）",
  }));

  function selectTract(next: string) {
    setTractId(next);
    setParams({ tract_id: next });
  }

  return (
    <div style={STAGE_WRAP}>
      {isLoading ? (
        <div style={CENTER}>
          <Spin />
        </div>
      ) : active ? (
        <TemporalCompare
          key={active.tract_id}
          phases={active.phases}
          range={range}
          onRangeChange={setRange}
          center={active.center}
          zoom={15}
          basemap={basemapById(basemapId)}
          roadOverlay={roadOverlay}
          onWipeApi={setWipeApi}
        />
      ) : (
        <div style={CENTER}>
          <Empty description="暂无可对比地块" />
        </div>
      )}

      <Card style={PANEL} styles={CARD_STYLES} title="时相对比">
        <Space direction="vertical" size={8} style={FULL}>
          <Select
            style={FULL}
            placeholder="选择地块"
            value={active?.tract_id}
            options={options}
            onChange={selectTract}
            disabled={groups.length === 0}
          />
          <Text type="secondary">{active ? active.phases.length + " 个时相" : "无时相"}</Text>
        </Space>
      </Card>

      <MapFloatingToolbar
        basemapId={basemapId}
        onBasemapChange={setBasemapId}
        roadVisible={roadVisible}
        onRoadVisibleChange={setRoadVisible}
        homeTitle="回到地块视野"
        onZoomIn={() => wipeApi?.zoomIn()}
        onZoomOut={() => wipeApi?.zoomOut()}
        onHome={() => wipeApi?.fitToData()}
        onResetNorth={() => wipeApi?.resetNorth()}
      />

      {active && active.phases.length > 1 ? (
        <ChangeMetricsPanel phases={active.phases} range={range} />
      ) : null}
    </div>
  );
}

function buildCompareGroups(tracts: Tract[]): CompareGroup[] {
  const byTract = new Map<string, Tract[]>();
  for (const tract of tracts) {
    const tract_id = tract.tract_id;
    const arr = byTract.get(tract_id) ?? [];
    arr.push(tract);
    byTract.set(tract_id, arr);
  }

  const fallbackCenter = centerOfBounds(env.overviewBounds);
  const groups: CompareGroup[] = [];
  for (const [tract_id, items] of byTract) {
    const sorted = [...items].sort(compareTractTime);
    const centerSource = [...sorted].reverse().find((t) => tractCenter(t));
    groups.push({
      tract_id,
      phases: sorted.map((tract) => ({
        id: String(tract.tract_phase_pk || tract.tract_id),
        label: tract_id + " · " + (tract.phase_id || "未知时相"),
        time: tract.phase_id || "",
      })),
      center: centerSource ? tractCenter(centerSource) ?? fallbackCenter : fallbackCenter,
    });
  }
  groups.sort(
    (a, b) =>
      b.phases.length - a.phases.length
      || a.tract_id.localeCompare(b.tract_id, "zh-Hans-CN"),
  );
  return groups;
}

function compareTractTime(a: Tract, b: Tract): number {
  return String(a.phase_id || "").localeCompare(String(b.phase_id || ""));
}

function centerOfBounds(bounds: [LngLat, LngLat]): LngLat {
  return [
    (bounds[0][0] + bounds[1][0]) / 2,
    (bounds[0][1] + bounds[1][1]) / 2,
  ];
}

const STAGE_WRAP: CSSProperties = {
  position: "relative",
  flex: 1,
  minHeight: 0,
};
const CENTER: CSSProperties = {
  position: "absolute",
  inset: 0,
  display: "flex",
  justifyContent: "center",
  alignItems: "center",
};
const PANEL: CSSProperties = {
  position: "absolute",
  top: 16,
  left: 16,
  width: 300,
  zIndex: 6,
  boxShadow: "var(--shadow-2)",
};
const PANEL_BODY: CSSProperties = { paddingTop: 4 };
const CARD_STYLES = { body: PANEL_BODY };
const FULL: CSSProperties = { width: "100%" };
