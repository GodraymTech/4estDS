import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { Checkbox, Empty, Select, Space, Spin } from "antd";
import { useSearchParams } from "react-router-dom";
import { useTracts, type Tract } from "../entities/tract";
import { useObservations } from "../entities/observation";
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
import { MapGlassPanel } from "../shared/ui/MapGlassPanel";
import type { TemporalWipeApi } from "../shared/ui/TemporalWipe";

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
  const [roadVisible, setRoadVisible] = useState(false);
  const [wipeApi, setWipeApi] = useState<TemporalWipeApi | null>(null);
  const [showDetections, setShowDetections] = useState(true);
  const [selectedSpecies, setSelectedSpecies] = useState<string[]>([]);

  const active = useMemo(() => {
    if (groups.length === 0) return undefined;
    return (
      groups.find((g) => g.tract_id === tractId)
      ?? groups.find((g) => g.tract_id === requestedTractId)
      ?? groups[0]
    );
  }, [groups, tractId, requestedTractId]);

  const [range, setRange] = useState<[number, number]>([0, 0]);
  const beforePhase = active?.phases[range[0]];
  const afterPhase = active?.phases[range[1]];
  const beforeObs = useObservations(beforePhase?.id, "crown");
  const afterObs = useObservations(afterPhase?.id, "crown");
  const comparedSpecies = useMemo(
    () => collectSpecies(beforeObs.data, afterObs.data),
    [afterObs.data, beforeObs.data],
  );
  const roadOverlay = useMemo(
    () => roadVisible
      ? { ...ROAD_OVERLAY, opacity: basemapId === "satellite" ? 0.52 : 0.24 }
      : null,
    [basemapId, roadVisible],
  );

  const lastTractId = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (!active) return;
    if (active.tract_id !== lastTractId.current) {
      lastTractId.current = active.tract_id;
      setRange(pickLatestTwo(active.phases));
    }
  }, [active]);

  useEffect(() => {
    setSelectedSpecies(comparedSpecies);
  }, [afterPhase?.id, beforePhase?.id, comparedSpecies]);

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
          showDetections={showDetections}
          selectedSpecies={selectedSpecies}
        />
      ) : (
        <div style={CENTER}>
          <Empty description="暂无可对比地块" />
        </div>
      )}

      <MapGlassPanel style={PANEL} title="时相对比">
        <Space direction="vertical" size={8} style={FULL}>
          <Select
            style={FULL}
            placeholder="选择地块"
            value={active?.tract_id}
            options={options}
            onChange={selectTract}
            disabled={groups.length === 0}
          />
          <div style={DETECTION_MODULE}>
            <Checkbox checked={showDetections} onChange={(event) => setShowDetections(event.target.checked)}>
              显示检测框
            </Checkbox>
            {showDetections && comparedSpecies.length > 0 ? (
              <Checkbox.Group
                value={selectedSpecies}
                onChange={(values) => setSelectedSpecies(values.map(String))}
                style={SPECIES_GRID}
              >
                {comparedSpecies.map((species, index) => (
                  <Checkbox key={species} value={species} style={SPECIES_CHECK}>
                    <span style={SPECIES_LABEL}>
                      <i style={{ ...SPECIES_DOT, background: BEFORE_SPECIES_COLORS[index % BEFORE_SPECIES_COLORS.length] }} />
                      <i style={{ ...SPECIES_DOT, background: AFTER_SPECIES_COLORS[index % AFTER_SPECIES_COLORS.length] }} />
                      {species}
                    </span>
                  </Checkbox>
                ))}
              </Checkbox.Group>
            ) : null}
          </div>
        </Space>
      </MapGlassPanel>

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

function collectSpecies(
  before?: { features: Array<{ properties: Record<string, unknown> }> },
  after?: { features: Array<{ properties: Record<string, unknown> }> },
): string[] {
  const species = new Set<string>();
  for (const feature of [...(before?.features ?? []), ...(after?.features ?? [])]) {
    const value = feature.properties.species;
    species.add(typeof value === "string" && value.trim() ? value : "未知树种");
  }
  return [...species].sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
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
  width: 200,
  zIndex: 6,
};
const FULL: CSSProperties = { width: "100%" };
const BEFORE_SPECIES_COLORS = ["#f0b84f", "#e76f51", "#d1495b", "#b56576", "#9c6644", "#c77dff"];
const AFTER_SPECIES_COLORS = ["#33b27b", "#00a6a6", "#2a9d8f", "#4cc9f0", "#3a86ff", "#43aa8b"];
const DETECTION_MODULE: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 6,
  paddingTop: 8,
  borderTop: "1px solid var(--glass-border)",
};
const SPECIES_GRID: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(0, 1fr)",
  gap: 4,
};
const SPECIES_CHECK: CSSProperties = {
  marginInlineStart: 0,
  fontSize: 12,
  overflow: "hidden",
  whiteSpace: "nowrap",
  textOverflow: "ellipsis",
};
const SPECIES_LABEL: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  minWidth: 0,
  gap: 4,
};
const SPECIES_DOT: CSSProperties = {
  width: 7,
  height: 7,
  flex: "0 0 auto",
  borderRadius: "50%",
};
