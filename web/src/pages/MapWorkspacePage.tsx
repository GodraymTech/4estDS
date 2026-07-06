import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import {
  Button,
  Checkbox,
  Empty,
  Popover,
  Select,
  Space,
  Spin,
  Switch,
  Tooltip,
  Typography,
} from "antd";
import {
  BorderOutlined,
  CalendarOutlined,
  CompassOutlined,
  EyeInvisibleOutlined,
  EyeOutlined,
  HomeOutlined,
  LineChartOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MinusOutlined,
  PlusOutlined,
  SearchOutlined,
  SwapOutlined,
} from "@ant-design/icons";
import { useParams } from "react-router-dom";
import { MapStage } from "../shared/ui/MapStage";
import {
  BASEMAPS,
  ROAD_OVERLAY,
  basemapById,
  boundsOf,
  provinceBoundaryByName,
  provinceBounds,
  provinceMask,
  rasterBasemap,
  type BBox,
  type GeoJson,
  type GeoJsonLayerSpec,
  type LngLat,
  type MapController,
  type MarkerSpec,
} from "../shared/map-core";
import type { DistributionSummary } from "../shared/api";
import { env } from "../shared/config/env";
import type { GeoFeature } from "../shared/api";
import { useObservations, type FeatureCollection } from "../entities/observation";
import {
  useTractImagery,
  useTractSummary,
  useTracts,
  type Tract,
  type TractSummary,
} from "../entities/tract";
import { pickLatestTwo, type Phase } from "../entities/phase";
import { createTractMarkerElement } from "../features/overview/TractMarker";
import { tractCenter } from "../features/overview/tractGeo";
import {
  buildAreaGeoJson,
  buildLineGeoJson,
  buildPointsGeoJson,
  computeMeasure,
  formatArea,
  formatLength,
  type MeasureMode,
} from "../features/measure/measureModel";
import { buildChangeMetrics, toHectares } from "../features/change-metrics/metrics";
import { TemporalCompare } from "../features/temporal-wipe";

const { Text } = Typography;

const DETECTION_PREFIX = "detections-";
const IMAGERY_LAYER = "tract-imagery";
const ROAD_LAYER = "road-overlay";
const MASK_LAYER = "overview-mask";
const BOUNDARY_LAYER = "overview-boundary";
const MEASURE_PTS = "measure-pts";
const MEASURE_LINE = "measure-line";
const MEASURE_FILL = "measure-fill";
const EMPTY_TRACTS: Tract[] = [];
const OVERVIEW_FIT = {
  padding: { top: 84, right: 44, bottom: 96, left: 44 },
  maxZoom: env.overviewZoom,
  duration: 420,
};

const SPECIES_COLOR_OVERRIDES: Record<string, string> = {
  TREE: "#ef476f",
  "未知树种": "#118ab2",
  unknown: "#118ab2",
};

const OUTLINE_COLORS = [
  "#00b4d8",
  "#ffd166",
  "#2a9d8f",
  "#7b2cbf",
  "#f72585",
  "#80ffdb",
  "#ff9f1c",
];

const GUANGDONG_PLACES: Array<{ name: string; center: LngLat; zoom: number }> = [
  { name: "广东", center: [113.27, 23.13], zoom: 7 },
  { name: "广州", center: [113.2644, 23.1291], zoom: 11 },
  { name: "深圳", center: [114.0579, 22.5431], zoom: 11 },
  { name: "珠海", center: [113.5767, 22.2707], zoom: 11 },
  { name: "汕头", center: [116.6819, 23.3541], zoom: 11 },
  { name: "佛山", center: [113.1214, 23.0215], zoom: 11 },
  { name: "湛江", center: [110.3594, 21.2707], zoom: 11 },
  { name: "徐闻", center: [110.175, 20.3261], zoom: 12 },
  { name: "雷州", center: [110.0965, 20.9144], zoom: 12 },
  { name: "阳江", center: [111.9822, 21.8579], zoom: 11 },
  { name: "茂名", center: [110.9255, 21.6627], zoom: 11 },
  { name: "惠州", center: [114.4168, 23.1123], zoom: 11 },
  { name: "东莞", center: [113.7518, 23.0207], zoom: 11 },
  { name: "江门", center: [113.0819, 22.5787], zoom: 11 },
  { name: "中山", center: [113.3926, 22.5159], zoom: 11 },
];

interface PlotGroup {
  key: string;
  label: string;
  tracts: Tract[];
  latest: Tract;
  center: LngLat;
}

interface HoveredPlot {
  group: PlotGroup;
  x: number;
  y: number;
}

export function MapWorkspacePage() {
  const { tractId } = useParams();
  const { data: tracts, error: tractsError, isError: tractsFailed, isLoading } = useTracts();
  const [map, setMap] = useState<MapController | null>(null);
  const [ready, setReady] = useState(false);
  const [hovered, setHovered] = useState<HoveredPlot | null>(null);
  const [selectedId, setSelectedId] = useState<string | undefined>(undefined);
  const [basemapId, setBasemapId] = useState(env.defaultBasemapId);
  const [roadVisible, setRoadVisible] = useState(true);
  const [showDetections, setShowDetections] = useState(true);
  const [selectedSpecies, setSelectedSpecies] = useState<string[]>([]);
  const [compareMode, setCompareMode] = useState(false);
  const [range, setRange] = useState<[number, number]>([0, 0]);
  const [zoom, setZoom] = useState(env.overviewZoom);
  const [searchOpen, setSearchOpen] = useState(false);
  const [measureMode, setMeasureMode] = useState<MeasureMode>("idle");
  const [measureCoords, setMeasureCoords] = useState<LngLat[]>([]);
  const [chromeHidden, setChromeHidden] = useState(false);
  const detectionLayerIds = useRef<string[]>([]);
  const fittedTract = useRef<string | null>(null);

  const overviewBoundary = useMemo(
    () => provinceBoundaryByName(env.overviewRegion),
    [],
  );
  const overviewBounds = useMemo(
    () => provinceBounds(overviewBoundary) ?? env.overviewBounds,
    [overviewBoundary],
  );
  const overviewMaxBounds = useMemo(
    () => expandBounds(overviewBounds, 0.12, 0.18),
    [overviewBounds],
  );
  const list = tracts ?? EMPTY_TRACTS;
  const plotGroups = useMemo(() => buildPlotGroups(list), [list]);
  const overviewStats = useMemo(() => buildOverviewStats(list, plotGroups), [list, plotGroups]);
  const searchOptions = useMemo(() => buildSearchOptions(plotGroups), [plotGroups]);
  const groupByTract = useMemo(() => mapTractToGroup(plotGroups), [plotGroups]);
  const selected = useMemo(
    () => list.find((t) => t.tract_id === selectedId),
    [list, selectedId],
  );
  const selectedGroup = selected ? groupByTract.get(selected.tract_id) : undefined;
  const phases = useMemo(
    () => (selectedGroup ? toPhases(selectedGroup) : []),
    [selectedGroup],
  );
  const activeTract = compareMode && selectedGroup
    ? selectedGroup.tracts[range[1]] ?? selectedGroup.latest
    : selected;

  const observations = useObservations(activeTract?.tract_id, "crown");
  const imagery = useTractImagery(activeTract?.tract_id);
  const summary = useTractSummary(activeTract?.tract_id);
  const speciesList = useMemo(
    () => extractSpecies(observations.data),
    [observations.data],
  );
  const speciesColors = useMemo(
    () => buildSpeciesColorMap(speciesList),
    [speciesList],
  );

  const missingCoords = Math.max(0, list.length - plotGroups.reduce((n, g) => n + g.tracts.length, 0));

  useEffect(() => {
    if (tractId && list.some((t) => t.tract_id === tractId)) {
      setSelectedId(tractId);
    }
  }, [tractId, list]);

  useEffect(() => {
    setSelectedSpecies(speciesList);
  }, [speciesList.join("|")]);

  useEffect(() => {
    if (selectedGroup) setRange(pickLatestTwo(toPhases(selectedGroup)));
  }, [selectedGroup]);

  const syncMask = useCallback((ctl: MapController) => {
    ctl.removeLayer(MASK_LAYER);
    ctl.removeLayer(BOUNDARY_LAYER);
    ctl.setGeoJsonLayer({
      id: MASK_LAYER,
      kind: "polygon",
      data: provinceMask(overviewBoundary, overviewBounds),
      color: "#030504",
      opacity: 0.82,
    });
    if (overviewBoundary) {
      ctl.setGeoJsonLayer({
        id: BOUNDARY_LAYER,
        kind: "line",
        data: overviewBoundary,
        color: "#e8fff9",
        opacity: 0.78,
        lineWidth: 1.4,
      });
    }
  }, [overviewBoundary, overviewBounds]);

  const onReady = useCallback(
    (ctl: MapController) => {
      setMap(ctl);
      setReady(true);
      ctl.setMaxBounds(overviewMaxBounds);
      ctl.setMinZoom(env.overviewMinZoom);
      ctl.fitBounds(overviewBounds, OVERVIEW_FIT);
      syncMask(ctl);
      setZoom(ctl.getZoom());
    },
    [overviewBounds, overviewMaxBounds, syncMask],
  );

  useEffect(() => {
    if (!map || !ready) return;
    const off = map.on("move", () => setZoom(map.getZoom()));
    return off;
  }, [map, ready]);

  useEffect(() => {
    if (!map || !ready) return;
    map.setBasemap(basemapById(basemapId));
  }, [basemapId, map, ready]);

  useEffect(() => {
    if (!map || !ready) return;
    if (roadVisible) {
      map.setRasterOverlay(ROAD_LAYER, {
        ...ROAD_OVERLAY,
        opacity: basemapId === "satellite" ? 0.52 : 0.24,
      });
    } else {
      map.removeRasterOverlay(ROAD_LAYER);
    }
    syncMask(map);
  }, [basemapId, map, ready, roadVisible, syncMask]);

  useEffect(() => {
    if (!map || !ready) return;
    if (selectedId) {
      setHovered(null);
      map.setMarkers([]);
      return;
    }
    const markers: MarkerSpec[] = plotGroups.map((group) => {
      const element = createTractMarkerElement(Boolean(group.latest.active_run_id), {
        onClick: () => selectGroup(group),
        onEnter: (rect) =>
          setHovered({ group, x: rect.left + rect.width / 2, y: rect.top }),
        onLeave: () => setHovered(null),
      });
      return { id: group.key, lngLat: group.center, element };
    });
    map.setMarkers(markers);
  }, [map, plotGroups, ready, selectedId]);

  useEffect(() => {
    if (!map || !ready) return;
    if (activeTract && imagery.data?.available && imagery.data.tiles?.length) {
      map.setRasterOverlay(
        IMAGERY_LAYER,
        rasterBasemap(imagery.data.tiles, {
          tileSize: imagery.data.tile_size,
          attribution: imagery.data.attribution ?? undefined,
          minZoom: imagery.data.min_zoom,
          maxZoom: imagery.data.max_zoom,
        }),
      );
    } else {
      map.removeRasterOverlay(IMAGERY_LAYER);
    }
  }, [activeTract, imagery.data, map, ready]);

  useEffect(() => {
    if (!map || !ready) return;
    clearDetectionLayers(map, detectionLayerIds.current);
    detectionLayerIds.current = [];
    if (!showDetections || !observations.data) return;
    if (speciesList.length > 0 && selectedSpecies.length === 0) return;
    const layers = buildSpeciesLayers(observations.data, selectedSpecies, speciesColors);
    for (const layer of layers) {
      map.setGeoJsonLayer(layer);
      detectionLayerIds.current.push(layer.id);
    }
  }, [map, observations.data, ready, selectedSpecies, showDetections, speciesColors, speciesList.length]);

  useEffect(() => {
    if (!map || !ready || !activeTract || !observations.data) return;
    if (fittedTract.current === activeTract.tract_id) return;
    fittedTract.current = activeTract.tract_id;
    const b = boundsOf(observations.data as GeoJson);
    if (b) {
      map.fitBounds(b, 88);
      return;
    }
    const group = groupByTract.get(activeTract.tract_id);
    if (group) map.flyTo(group.center, 15);
  }, [activeTract, groupByTract, map, observations.data, ready]);

  useEffect(() => {
    if (!map || !ready || measureMode === "idle") return;
    map.setCursor("crosshair");
    const off = map.on("mapClick", (p) => setMeasureCoords((prev) => [...prev, p as LngLat]));
    return () => {
      off();
      map.setCursor(null);
    };
  }, [map, measureMode, ready]);

  useEffect(() => {
    if (!map || !ready) return;
    if (measureMode === "idle") {
      clearMeasureLayers(map);
      return;
    }
    if (measureMode === "area") {
      map.setGeoJsonLayer({
        id: MEASURE_FILL,
        kind: "polygon",
        data: buildAreaGeoJson(measureCoords),
        color: "#f4a261",
        opacity: 0.24,
      });
    } else {
      map.removeLayer(MEASURE_FILL);
    }
    map.setGeoJsonLayer({
      id: MEASURE_LINE,
      kind: "line",
      data: buildLineGeoJson(measureCoords),
      color: "#ef476f",
      dashArray: [2, 1],
    });
    map.setGeoJsonLayer({
      id: MEASURE_PTS,
      kind: "point",
      data: buildPointsGeoJson(measureCoords),
      color: "#10302b",
    });
  }, [map, measureCoords, measureMode, ready]);

  function selectGroup(group: PlotGroup) {
    setSelectedId(group.latest.tract_id);
    setCompareMode(false);
    fittedTract.current = null;
    map?.flyTo(group.center, 15);
  }

  function selectPhaseTract(tract: Tract) {
    setSelectedId(tract.tract_id);
    setCompareMode(false);
    fittedTract.current = null;
  }

  function selectSearch(key: string) {
    const group = plotGroups.find((g) => g.key === key);
    if (group) {
      selectGroup(group);
      return;
    }
    const place = GUANGDONG_PLACES.find((p) => "place:" + p.name === key);
    if (place) {
      setSelectedId(undefined);
      setCompareMode(false);
      fittedTract.current = null;
      map?.flyTo(place.center, place.zoom);
    }
  }

  function resetNorth() {
    if (!map) return;
    map.jumpTo({ ...map.getCamera(), bearing: 0, pitch: 0 });
  }

  function returnOverview() {
    setSelectedId(undefined);
    setCompareMode(false);
    setMeasureMode("idle");
    setMeasureCoords([]);
    fittedTract.current = null;
    if (map) {
      clearDetectionLayers(map, detectionLayerIds.current);
      detectionLayerIds.current = [];
      clearMeasureLayers(map);
      map.removeRasterOverlay(IMAGERY_LAYER);
      map.fitBounds(overviewBounds, OVERVIEW_FIT);
    }
  }

  const measure = useMemo(
    () => computeMeasure(measureMode, measureCoords),
    [measureCoords, measureMode],
  );

  return (
    <div style={ROOT}>
      <MapStage
        center={centerOfBounds(overviewBounds)}
        zoom={env.overviewZoom}
        onReady={onReady}
      />

      {compareMode && selectedGroup && phases.length > 1 ? (
        <TemporalCompare
          phases={phases}
          range={range}
          onRangeChange={(v) => {
            setRange(v);
            const next = selectedGroup.tracts[v[1]];
            if (next) setSelectedId(next.tract_id);
          }}
          center={selectedGroup.center}
          zoom={Math.max(zoom, 15)}
        />
      ) : null}

      {chromeHidden ? (
        <button
          type="button"
          style={RESTORE_TRIGGER}
          aria-label="恢复浮动模块"
          onClick={() => setChromeHidden(false)}
        >
          <MenuUnfoldOutlined />
          <span>恢复</span>
        </button>
      ) : searchOpen ? (
        <div style={SEARCH_PANEL}>
          <SearchOutlined style={SEARCH_ICON} />
          <Select
            autoFocus
            allowClear
            showSearch
            value={selectedGroup?.key}
            placeholder="搜索"
            options={searchOptions}
            filterOption={(input, option) =>
              String(option?.label ?? "").toLowerCase().includes(input.toLowerCase())
            }
            notFoundContent="本地未命中"
            onChange={(v) => {
              if (v) selectSearch(v);
              else returnOverview();
              setSearchOpen(false);
            }}
            onBlur={() => {
              if (!selectedGroup) setSearchOpen(false);
            }}
            style={SEARCH_SELECT}
            variant="borderless"
          />
        </div>
      ) : (
        <button
          type="button"
          style={SEARCH_TRIGGER}
          aria-label="搜索"
          onClick={() => setSearchOpen(true)}
        >
          <SearchOutlined />
        </button>
      )}

      {!chromeHidden && selectedGroup ? (
        <button
          type="button"
          style={{
            ...COMPARE_FLOAT_BUTTON,
            left: searchOpen ? 234 : 60,
            ...(compareMode ? COMPARE_FLOAT_BUTTON_ACTIVE : null),
            opacity: selectedGroup.tracts.length < 2 ? 0.54 : 1,
          }}
          disabled={selectedGroup.tracts.length < 2}
          onClick={() => setCompareMode((v) => !v)}
        >
          <SwapOutlined />
          <span>时相对比</span>
        </button>
      ) : null}

      {!chromeHidden ? (
        <div style={TOP_TOOLBAR}>
          <div style={LAYER_PANEL}>
            <Select
              size="small"
              value={basemapId}
              onChange={setBasemapId}
              options={BASEMAPS.map((b) => ({ value: b.id, label: b.label }))}
              style={BASEMAP_SELECT}
            />
            <Space size={8}>
              <Text style={PANEL_TEXT}>路网</Text>
              <Switch size="small" checked={roadVisible} onChange={setRoadVisible} />
            </Space>
          </div>

          <div style={RIGHT_TOOLS}>
            <ToolButton title="放大" icon={<PlusOutlined />} onClick={() => map?.zoomIn()} />
            <div style={ZOOM_BADGE}>{zoom.toFixed(1)}</div>
            <ToolButton title="缩小" icon={<MinusOutlined />} onClick={() => map?.zoomOut()} />
            <ToolButton title="回到总观视野" icon={<HomeOutlined />} onClick={returnOverview} />
            <ToolButton
              title="测长度"
              active={measureMode === "distance"}
              icon={<LineChartOutlined />}
              onClick={() => {
                setMeasureMode((m) => (m === "distance" ? "idle" : "distance"));
                setMeasureCoords([]);
              }}
            />
            <ToolButton
              title="测面积"
              active={measureMode === "area"}
              icon={<BorderOutlined />}
              onClick={() => {
                setMeasureMode((m) => (m === "area" ? "idle" : "area"));
                setMeasureCoords([]);
              }}
            />
            <ToolButton
              title="隐藏浮动模块"
              icon={<MenuFoldOutlined />}
              onClick={() => setChromeHidden(true)}
            />
          </div>
        </div>
      ) : null}

      {!chromeHidden ? (
        <div style={COMPASS_PANEL}>
          <ToolButton title="指北" icon={<CompassOutlined />} onClick={resetNorth} />
        </div>
      ) : null}

      {!chromeHidden && measureMode !== "idle" ? (
        <div style={MEASURE_READOUT}>
          <Text style={READOUT_MAIN}>
            {measureMode === "distance"
              ? formatLength(measure.length)
              : formatArea(measure.area)}
          </Text>
          <Text style={READOUT_SUB}>
            {measure.points} 点
            {measureMode === "area" ? " · 周长 " + formatLength(measure.length) : ""}
          </Text>
          <Button size="small" onClick={() => setMeasureCoords([])} disabled={measure.points === 0}>
            清除
          </Button>
        </div>
      ) : null}

      {!chromeHidden && selectedGroup && activeTract ? (
        compareMode ? (
          <ChangeCompactCard phases={phases} range={range} />
        ) : (
          <ProfilePanel
            tract={activeTract}
            group={selectedGroup}
            imagery={imagery.data}
            summary={summary.data}
            speciesColors={speciesColors}
            onSelectPhase={selectPhaseTract}
            loading={observations.isFetching || imagery.isFetching || summary.isFetching}
          />
        )
      ) : null}

      {!chromeHidden && !selectedGroup ? <OverviewProfileCard stats={overviewStats} /> : null}

      {!chromeHidden && selectedGroup && activeTract ? (
        <div style={TRACT_TOOLS}>
          <Space direction="vertical" size={6} style={FULL}>
            <Space size={6} wrap>
              <Button
                size="small"
                type={showDetections ? "primary" : "default"}
                icon={showDetections ? <EyeOutlined /> : <EyeInvisibleOutlined />}
                onClick={() => setShowDetections((v) => !v)}
              >
                显示检测框
              </Button>
            </Space>
            {showDetections && speciesList.length > 0 ? (
              <Checkbox.Group
                value={selectedSpecies}
                onChange={(values) => setSelectedSpecies(values.map(String))}
                style={SPECIES_GRID}
              >
                {speciesList.map((species, idx) => (
                  <Checkbox key={species} value={species} style={SPECIES_CHECK}>
                    <span
                      style={{
                        ...SPECIES_DOT,
                        background: speciesColors.get(species) ?? speciesColor(species, idx),
                      }}
                    />
                    {species}
                  </Checkbox>
                ))}
              </Checkbox.Group>
            ) : null}
          </Space>
        </div>
      ) : null}

      {!chromeHidden && hovered ? <PlotHoverCard hovered={hovered} /> : null}

      {isLoading ? (
        <div style={LOADING}>
          <Spin />
        </div>
      ) : tractsFailed ? (
        <div style={EMPTY}>
          <Empty
            description={
              "地块接口请求失败: "
              + (tractsError instanceof Error ? tractsError.message : "请检查后端服务")
            }
          />
        </div>
      ) : plotGroups.length === 0 ? (
        <div style={EMPTY}>
          <Empty description="暂无可上图地块" />
        </div>
      ) : null}

      {!chromeHidden && missingCoords > 0 ? (
        <div style={STATUS_CHIP}>{missingCoords} 个地块缺少空间坐标</div>
      ) : null}
    </div>
  );
}

function buildPlotGroups(tracts: Tract[]): PlotGroup[] {
  const byKey = new Map<string, Tract[]>();
  for (const tract of tracts) {
    const key = tract.location || tract.name || tract.tract_id;
    const arr = byKey.get(key) ?? [];
    arr.push(tract);
    byKey.set(key, arr);
  }
  const groups: PlotGroup[] = [];
  for (const [key, arr] of byKey) {
    const sorted = [...arr].sort(compareTractTime);
    const latest = sorted[sorted.length - 1];
    const centerSource = [...sorted].reverse().find((t) => tractCenter(t));
    const center = centerSource ? tractCenter(centerSource) : null;
    if (!center) continue;
    groups.push({
      key,
      label: latest.name || latest.location || latest.tract_id,
      tracts: sorted,
      latest,
      center,
    });
  }
  groups.sort((a, b) => a.label.localeCompare(b.label, "zh-Hans-CN"));
  return groups;
}

function mapTractToGroup(groups: PlotGroup[]): Map<string, PlotGroup> {
  const out = new Map<string, PlotGroup>();
  for (const group of groups) {
    for (const tract of group.tracts) out.set(tract.tract_id, group);
  }
  return out;
}

function buildSearchOptions(groups: PlotGroup[]) {
  return [
    {
      label: "地块",
      options: groups.map((g) => ({ value: g.key, label: g.label })),
    },
    {
      label: "地名",
      options: GUANGDONG_PLACES.map((p) => ({
        value: "place:" + p.name,
        label: p.name,
      })),
    },
  ];
}

function buildOverviewStats(tracts: Tract[], groups: PlotGroup[]) {
  const area = tracts.reduce((sum, t) => sum + (t.geo_area ?? 0), 0);
  const trees = tracts.reduce((sum, t) => sum + (t.observation_count ?? 0), 0);
  const located = tracts.filter((t) => tractCenter(t)).length;
  const published = tracts.filter((t) => t.active_run_id).length;
  return {
    groups: groups.length,
    phases: tracts.length,
    area,
    trees,
    located,
    published,
  };
}

function compareTractTime(a: Tract, b: Tract): number {
  return String(a.acquisition_time || "").localeCompare(String(b.acquisition_time || ""));
}

function toPhases(group: PlotGroup): Phase[] {
  return group.tracts.map((tract) => ({
    id: tract.tract_id,
    label: group.label + " · " + (tract.acquisition_time || "未知时相"),
    time: tract.acquisition_time || "",
  }));
}

function extractSpecies(fc?: FeatureCollection): string[] {
  const set = new Set<string>();
  for (const feature of fc?.features ?? []) {
    const raw = feature.properties?.species;
    set.add(typeof raw === "string" && raw.trim() ? raw : "未知树种");
  }
  return [...set].sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
}

function speciesColor(species: string, indexHint = 0): string {
  const override = SPECIES_COLOR_OVERRIDES[species] ?? SPECIES_COLOR_OVERRIDES[species.toUpperCase()];
  if (override) return override;
  return OUTLINE_COLORS[Math.abs(indexHint) % OUTLINE_COLORS.length];
}

function buildSpeciesColorMap(speciesList: string[]): Map<string, string> {
  const colors = new Map<string, string>();
  const used = new Set<string>();
  for (const species of speciesList) {
    const override = SPECIES_COLOR_OVERRIDES[species] ?? SPECIES_COLOR_OVERRIDES[species.toUpperCase()];
    if (override) {
      colors.set(species, override);
      used.add(override.toLowerCase());
    }
  }
  let idx = 0;
  for (const species of speciesList) {
    if (colors.has(species)) continue;
    let color = OUTLINE_COLORS[idx % OUTLINE_COLORS.length];
    while (used.has(color.toLowerCase())) {
      idx += 1;
      color = OUTLINE_COLORS[idx % OUTLINE_COLORS.length];
    }
    colors.set(species, color);
    used.add(color.toLowerCase());
    idx += 1;
  }
  return colors;
}

function buildSpeciesLayers(
  fc: FeatureCollection,
  selectedSpecies: string[],
  colors: Map<string, string>,
): GeoJsonLayerSpec[] {
  const allowed = new Set(selectedSpecies);
  const bySpecies = new Map<string, GeoFeature[]>();
  for (const feature of fc.features) {
    const raw = feature.properties?.species;
    const species = typeof raw === "string" && raw.trim() ? raw : "未知树种";
    if (allowed.size > 0 && !allowed.has(species)) continue;
    const arr = bySpecies.get(species) ?? [];
    arr.push(feature);
    bySpecies.set(species, arr);
  }
  return [...bySpecies.entries()].map(([species, features], idx) => ({
    id: DETECTION_PREFIX + safeLayerId(species),
    kind: "line" as const,
    color: colors.get(species) ?? speciesColor(species, idx),
    opacity: 0.96,
    lineWidth: 2.2,
    data: { type: "FeatureCollection", features } as GeoJson,
  }));
}

function safeLayerId(value: string): string {
  return encodeURIComponent(value).replace(/%/g, "_");
}

function clearDetectionLayers(map: MapController, ids: string[]) {
  for (const id of ids) map.removeLayer(id);
}

function clearMeasureLayers(map: MapController) {
  map.removeLayer(MEASURE_FILL);
  map.removeLayer(MEASURE_LINE);
  map.removeLayer(MEASURE_PTS);
}

function ToolButton({
  title,
  icon,
  onClick,
  active,
}: {
  title: string;
  icon: ReactNode;
  onClick: () => void;
  active?: boolean;
}) {
  return (
    <Tooltip title={title} placement="bottom">
      <Button
        type="text"
        icon={icon}
        onClick={onClick}
        style={active ? ACTIVE_TOOL_BUTTON : TOOL_BUTTON}
      />
    </Tooltip>
  );
}

function OverviewProfileCard({ stats }: { stats: ReturnType<typeof buildOverviewStats> }) {
  return (
    <div style={OVERVIEW_PROFILE}>
      <div style={PANEL_HEAD}>
        <span style={PANEL_TITLE}>总体核查进度</span>
      </div>
      <div style={OVERVIEW_KPI_GRID}>
        <CompactKpi label="地块" value={String(stats.groups)} />
        <CompactKpi label="时相" value={String(stats.phases)} />
        <CompactKpi label="面积" value={formatAreaValue(stats.area)} wide />
        <CompactKpi label="株数" value={stats.trees.toLocaleString()} wide />
        <CompactKpi label="定位" value={`${stats.located}/${stats.phases}`} />
        <CompactKpi label="发布" value={`${stats.published}/${stats.phases}`} />
      </div>
    </div>
  );
}

function CompactKpi({ label, value, wide }: { label: string; value: ReactNode; wide?: boolean }) {
  return (
    <div style={{ ...COMPACT_KPI, gridColumn: wide ? "span 2" : undefined }}>
      <span style={COMPACT_LABEL}>{label}</span>
      <span style={COMPACT_VALUE}>{value}</span>
    </div>
  );
}

function ProfilePanel({
  tract,
  group,
  imagery,
  summary,
  speciesColors,
  onSelectPhase,
  loading,
}: {
  tract: Tract;
  group: PlotGroup;
  imagery?: { available: boolean; source_format?: string | null; tile_service?: string | null };
  summary?: TractSummary;
  speciesColors: Map<string, string>;
  onSelectPhase: (tract: Tract) => void;
  loading: boolean;
}) {
  const meta = summary?.meta;
  const metricSections = buildProfileMetricSections(summary, tract, speciesColors);
  return (
    <div style={PROFILE_PANEL}>
      <div style={PANEL_HEAD}>
        <div style={PROFILE_TITLE_GROUP}>
          <span style={PANEL_TITLE}>{tract.name || tract.location || tract.tract_id}</span>
          <span style={PANEL_SUBTITLE}>时相ID {tract.acquisition_time || "未知时相"}</span>
        </div>
        <Space size={6}>
          <Popover
            trigger="click"
            placement="rightTop"
            styles={{ body: POPOVER_BODY }}
            content={
              <div style={PHASE_POPOVER}>
                {group.tracts.map((phase) => (
                  <button
                    key={phase.tract_id}
                    type="button"
                    style={phase.tract_id === tract.tract_id ? PHASE_OPTION_ACTIVE : PHASE_OPTION}
                    onClick={() => onSelectPhase(phase)}
                  >
                    <span>{phase.acquisition_time || "未知时相"}</span>
                    <strong>{(phase.observation_count ?? 0).toLocaleString()} 株</strong>
                  </button>
                ))}
              </div>
            }
          >
            <Button size="small" type="text" icon={<CalendarOutlined />} style={PHASE_PICKER_BUTTON}>
              时相选择
            </Button>
          </Popover>
          {loading ? <Spin size="small" /> : null}
        </Space>
      </div>
      <div style={PROFILE_PRIMARY_GRID}>
        <ProfileBigMetric label="面积" value={formatTractArea(tract)} />
        <ProfileBigMetric label="覆盖率" value={formatPercent(meta?.canopy_cover_rate)} />
      </div>
      <div style={PROFILE_SPECIES_LIST}>
        {metricSections.map((section) => (
          <ProfileMetricSection key={section.key} section={section} />
        ))}
      </div>
      <div style={PROFILE_TAGS}>
        <span style={MINI_TAG}>{group.tracts.length} 期</span>
        <span style={MINI_TAG}>{tract.active_run_id ? "已发布" : "最新成功 run"}</span>
        {imagery?.available ? <span style={MINI_TAG}>真影像</span> : null}
        {imagery?.source_format && !imagery.available ? (
          <span style={MINI_TAG}>{imagery.source_format}</span>
        ) : null}
      </div>
    </div>
  );
}

interface ProfileMetricSectionData {
  key: string;
  label: string;
  color: string;
  total?: boolean;
  count: number;
  ratio: number | null;
  density: number | null;
  crownArea: number;
  crownW?: DistributionSummary;
  crownH?: DistributionSummary;
  crownAreaDist?: DistributionSummary;
  height?: DistributionSummary;
}

function ProfileBigMetric({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div style={PROFILE_BIG_METRIC}>
      <span>{label}</span>
      <strong style={PROFILE_BIG_VALUE}>{value}</strong>
    </div>
  );
}

function ProfileMetricSection({ section }: { section: ProfileMetricSectionData }) {
  const headStyle = section.total ? PROFILE_SECTION_HEAD_TOTAL : PROFILE_SECTION_HEAD;
  const titleStyle = section.total ? PROFILE_SECTION_TITLE_TOTAL : PROFILE_SECTION_TITLE;
  return (
    <div style={section.total ? PROFILE_SECTION_TOTAL : PROFILE_SECTION}>
      <div style={headStyle}>
        <span style={{ ...SPECIES_DOT, background: section.color }} />
        <span style={titleStyle}>{section.label}</span>
      </div>
      <div style={PROFILE_QUAD_GRID}>
        <MiniMetric label="株数" value={section.count.toLocaleString()} />
        <MiniMetric label="占比" value={formatPercent(section.ratio)} />
        <MiniMetric label="密度" value={formatDensity(section.density)} />
        <MiniMetric label="冠幅和" value={formatAreaValue(section.crownArea)} />
      </div>
      <div style={PROFILE_DIST_STACK}>
        <ProfileDistRow label="冠尺寸" value={formatCrownSize(section.crownW, section.crownH)} />
        <ProfileDistRow label="冠面积" value={formatDistribution(section.crownAreaDist, "m²")} />
        {hasDistribution(section.height) ? (
          <ProfileDistRow label="树高" value={formatDistribution(section.height, "m")} />
        ) : null}
      </div>
    </div>
  );
}

function MiniMetric({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div style={MINI_METRIC}>
      <span>{label}</span>
      <strong style={MINI_METRIC_VALUE}>{value}</strong>
    </div>
  );
}

function ProfileDistRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={PROFILE_DIST_ROW}>
      <span>{label}</span>
      <strong style={PROFILE_DIST_VALUE}>{value}</strong>
    </div>
  );
}

function buildProfileMetricSections(
  summary: TractSummary | undefined,
  tract: Tract,
  speciesColors: Map<string, string>,
): ProfileMetricSectionData[] {
  const totalCount = summary?.tree_count ?? tract.observation_count ?? 0;
  const total: ProfileMetricSectionData = {
    key: "__total",
    label: "总体分析",
    color: "var(--glass-text)",
    total: true,
    count: totalCount,
    ratio: totalCount > 0 ? 1 : null,
    density: summary?.density_per_ha ?? densityFromCount(totalCount, tract.geo_area),
    crownArea: summary?.meta?.total_crown_area ?? 0,
    crownW: summary?.crown_w_geo,
    crownH: summary?.crown_h_geo,
    crownAreaDist: summary?.crown_area_geo,
    height: summary?.height,
  };
  const species = Object.entries(summary?.meta?.species_analysis ?? {})
    .sort(([, a], [, b]) => (b.count ?? 0) - (a.count ?? 0))
    .map(([label, item], idx) => {
      const count = item.count ?? 0;
      return {
        key: label,
        label,
        color: speciesColors.get(label) ?? speciesColor(label, idx),
        count,
        ratio: item.ratio ?? (totalCount > 0 ? count / totalCount : null),
        density: item.density_per_ha ?? densityFromCount(count, tract.geo_area),
        crownArea: item.total_crown_area ?? (item.avg_crown_area ?? 0) * count,
        crownW: item.crown_w_geo,
        crownH: item.crown_h_geo,
        crownAreaDist: item.crown_area_geo,
        height: item.height,
      } satisfies ProfileMetricSectionData;
    });
  return species.length <= 1 ? species : [total, ...species];
}

function ChangeCompactCard({ phases, range }: { phases: Phase[]; range: [number, number] }) {
  const before = phases[range[0]];
  const after = phases[range[1]];
  const beforeObs = useObservations(before?.id, "crown");
  const afterObs = useObservations(after?.id, "crown");
  const metrics = useMemo(
    () => buildChangeMetrics(beforeObs.data, afterObs.data),
    [beforeObs.data, afterObs.data],
  );
  const loading = beforeObs.isFetching || afterObs.isFetching;
  return (
    <div style={PROFILE_PANEL}>
      <div style={PANEL_HEAD}>
        <span style={PANEL_TITLE}>变化量</span>
        {loading ? <Spin size="small" /> : <SwapOutlined />}
      </div>
      <div style={CHANGE_GRID}>
        <Kpi label="株数变化" value={signed(metrics.countDelta, "株")} accent={metrics.countDelta >= 0 ? "up" : "down"} />
        <Kpi
          label="冠幅变化"
          value={signed(toHectares(metrics.areaDelta), "ha")}
          accent={metrics.areaDelta >= 0 ? "up" : "down"}
        />
        <Kpi label="基准时相" value={before?.time || "-"} />
        <Kpi label="目标时相" value={after?.time || "-"} />
      </div>
    </div>
  );
}

function PlotHoverCard({ hovered }: { hovered: HoveredPlot }) {
  const { group, x, y } = hovered;
  const style: CSSProperties = { ...HOVER_CARD, left: x, top: y };
  return (
    <div style={style}>
      <div style={HOVER_TITLE}>{group.label}</div>
      <div style={HOVER_ROW}>
        <span>最新时相</span>
        <strong>{group.latest.acquisition_time || "-"}</strong>
      </div>
      <div style={HOVER_ROW}>
        <span>时相数</span>
        <strong>{group.tracts.length}</strong>
      </div>
      <div style={HOVER_ROW}>
        <span>最新株数</span>
        <strong>{(group.latest.observation_count ?? 0).toLocaleString()}</strong>
      </div>
      <div style={HOVER_ROW}>
        <span>面积</span>
        <strong>{formatTractArea(group.latest)}</strong>
      </div>
    </div>
  );
}

function Kpi({
  label,
  value,
  accent,
}: {
  label: string;
  value: ReactNode;
  accent?: "up" | "down";
}) {
  const color = accent === "up" ? "#18794e" : accent === "down" ? "#b42318" : undefined;
  return (
    <div style={KPI}>
      <span style={KPI_LABEL}>{label}</span>
      <span style={{ ...KPI_VALUE, color }}>{value}</span>
    </div>
  );
}

function formatTractArea(tract: Tract): string {
  if (typeof tract.geo_area !== "number") return "-";
  return formatAreaValue(tract.geo_area);
}

function formatAreaValue(m2: number): string {
  if (m2 >= 1000000) return (m2 / 1000000).toFixed(3) + " km\u00b2";
  if (m2 >= 10000) return (m2 / 10000).toFixed(3) + " hm\u00b2";
  return m2.toLocaleString(undefined, { maximumFractionDigits: 1 }) + " m\u00b2";
}

function formatDensity(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return value.toLocaleString(undefined, { maximumFractionDigits: 1 }) + " 株/hm\u00b2";
}

function densityFromCount(count: number, areaM2: number | undefined): number | null {
  if (typeof areaM2 !== "number" || areaM2 <= 0) return null;
  return count / (areaM2 / 10000);
}

function formatPercent(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return (value * 100).toLocaleString(undefined, { maximumFractionDigits: 1 }) + "%";
}

function formatDistribution(dist: DistributionSummary | undefined, unit = ""): string {
  if (!dist || !dist.n) return "-";
  const median = formatMetric(dist.median);
  const p10 = formatMetric(dist.p10);
  const p90 = formatMetric(dist.p90);
  return `P50 ${median} · P10-90 ${p10}-${p90}${unit ? " " + unit : ""}`;
}

function formatCrownSize(
  width: DistributionSummary | undefined,
  height: DistributionSummary | undefined,
): string {
  if (!hasDistribution(width) || !hasDistribution(height)) return "-";
  const p50 = `${formatMetric(width.median)}x${formatMetric(height.median)}`;
  const p10 = `${formatMetric(width.p10)}x${formatMetric(height.p10)}`;
  const p90 = `${formatMetric(width.p90)}x${formatMetric(height.p90)}`;
  return `P50 ${p50} · P10-90 ${p10}-${p90} m`;
}

function hasDistribution(dist: DistributionSummary | undefined): dist is DistributionSummary {
  return Boolean(dist?.n && dist.n > 0);
}

function formatMetric(value: number | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function centerOfBounds(bounds: BBox): LngLat {
  return [
    (bounds[0][0] + bounds[1][0]) / 2,
    (bounds[0][1] + bounds[1][1]) / 2,
  ];
}

function expandBounds(bounds: BBox, lngRatio: number, latRatio: number): BBox {
  const [[west, south], [east, north]] = bounds;
  const dx = (east - west) * lngRatio;
  const dy = (north - south) * latRatio;
  return [
    [clamp(west - dx, -180, 180), clamp(south - dy, -85, 85)],
    [clamp(east + dx, -180, 180), clamp(north + dy, -85, 85)],
  ];
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function signed(value: number, unit: string): string {
  const sign = value >= 0 ? "+" : "-";
  return sign + Math.abs(value).toLocaleString() + " " + unit;
}

const FULL: CSSProperties = { width: "100%" };
const ROOT: CSSProperties = { position: "relative", flex: 1, minHeight: 0 };
const GLASS: CSSProperties = {
  background: "var(--glass-bg)",
  border: "1px solid var(--glass-border)",
  boxShadow: "var(--glass-shadow), var(--glass-inner)",
  backdropFilter: "saturate(1.85) blur(26px)",
  WebkitBackdropFilter: "saturate(1.85) blur(26px)",
};
const GLASS_ICON: CSSProperties = {
  ...GLASS,
  color: "var(--glass-text)",
};
const SEARCH_TRIGGER: CSSProperties = {
  ...GLASS_ICON,
  position: "absolute",
  top: 12,
  left: 12,
  zIndex: 8,
  width: 40,
  height: 40,
  borderRadius: 20,
  display: "grid",
  placeItems: "center",
  cursor: "pointer",
  fontSize: 15,
};
const SEARCH_PANEL: CSSProperties = {
  ...GLASS,
  position: "absolute",
  top: 12,
  left: 12,
  zIndex: 8,
  width: "min(210px, calc(100% - 104px))",
  height: 40,
  borderRadius: 20,
  display: "flex",
  alignItems: "center",
  paddingInline: 10,
};
const SEARCH_ICON: CSSProperties = { color: "var(--glass-text)", marginRight: 4, fontSize: 13 };
const SEARCH_SELECT: CSSProperties = { flex: 1 };
const COMPARE_FLOAT_BUTTON: CSSProperties = {
  ...GLASS,
  position: "absolute",
  top: 12,
  zIndex: 8,
  height: 40,
  borderRadius: 20,
  padding: "0 13px",
  display: "flex",
  alignItems: "center",
  gap: 6,
  border: "1px solid var(--glass-border)",
  color: "var(--glass-text)",
  fontSize: 12,
  fontWeight: 700,
  cursor: "pointer",
};
const COMPARE_FLOAT_BUTTON_ACTIVE: CSSProperties = {
  color: "#ffffff",
  background: "var(--color-primary)",
};
const TOP_TOOLBAR: CSSProperties = {
  position: "absolute",
  top: 12,
  right: 64,
  zIndex: 8,
  maxWidth: "calc(100% - 370px)",
  display: "flex",
  alignItems: "center",
  justifyContent: "flex-end",
  gap: 8,
  overflowX: "auto",
  scrollbarWidth: "none",
};
const LAYER_PANEL: CSSProperties = {
  ...GLASS,
  borderRadius: 14,
  padding: "6px 8px",
  display: "flex",
  alignItems: "center",
  gap: 8,
  flex: "0 0 auto",
};
const BASEMAP_SELECT: CSSProperties = { width: 76 };
const PANEL_TEXT: CSSProperties = { fontSize: 12, color: "var(--glass-text)" };
const RIGHT_TOOLS: CSSProperties = {
  ...GLASS,
  height: 42,
  borderRadius: 15,
  padding: 4,
  display: "flex",
  flexDirection: "row",
  alignItems: "center",
  gap: 2,
  flex: "0 0 auto",
};
const COMPASS_PANEL: CSSProperties = {
  ...GLASS,
  position: "absolute",
  right: 12,
  top: 12,
  zIndex: 8,
  width: 42,
  height: 42,
  borderRadius: 15,
  padding: 3,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
};
const TOOL_BUTTON: CSSProperties = {
  width: 34,
  height: 34,
  borderRadius: 11,
  color: "var(--glass-text)",
};
const ACTIVE_TOOL_BUTTON: CSSProperties = {
  ...TOOL_BUTTON,
  color: "#ffffff",
  background: "var(--color-primary)",
};
const RESTORE_TRIGGER: CSSProperties = {
  ...GLASS,
  position: "absolute",
  top: 12,
  right: 12,
  zIndex: 10,
  height: 40,
  borderRadius: 20,
  padding: "0 14px",
  display: "flex",
  alignItems: "center",
  gap: 6,
  border: "1px solid var(--glass-border)",
  color: "var(--glass-text)",
  fontWeight: 700,
  cursor: "pointer",
};
const ZOOM_BADGE: CSSProperties = {
  width: 38,
  height: 28,
  borderRadius: 10,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  fontSize: 12,
  fontVariantNumeric: "tabular-nums",
  color: "var(--glass-text)",
  background: "var(--glass-chip)",
};
const PROFILE_PANEL: CSSProperties = {
  ...GLASS,
  position: "absolute",
  left: 16,
  bottom: 16,
  zIndex: 8,
  width: "min(460px, calc(100vw - 32px))",
  maxHeight: "min(72vh, 680px)",
  overflowY: "auto",
  borderRadius: 18,
  padding: 12,
  color: "var(--glass-text)",
};
const OVERVIEW_PROFILE: CSSProperties = {
  ...GLASS,
  position: "absolute",
  right: 16,
  bottom: 16,
  zIndex: 8,
  width: 240,
  borderRadius: 18,
  padding: 12,
};
const PANEL_HEAD: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
  marginBottom: 10,
};
const PANEL_TITLE: CSSProperties = {
  fontSize: 15,
  fontWeight: 700,
  color: "var(--glass-text)",
};
const PANEL_SUBTITLE: CSSProperties = {
  color: "var(--glass-muted)",
  fontSize: 11,
  fontVariantNumeric: "tabular-nums",
};
const PHASE_PICKER_BUTTON: CSSProperties = {
  color: "var(--glass-text)",
  background: "var(--glass-chip)",
  borderRadius: 10,
};
const POPOVER_BODY: CSSProperties = {
  ...GLASS,
  padding: 6,
  borderRadius: 14,
  color: "var(--glass-text)",
};
const PHASE_POPOVER: CSSProperties = {
  minWidth: 178,
  display: "flex",
  flexDirection: "column",
  gap: 4,
};
const PHASE_OPTION: CSSProperties = {
  border: 0,
  borderRadius: 9,
  padding: "7px 8px",
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 12,
  color: "var(--color-text)",
  background: "transparent",
  cursor: "pointer",
  fontSize: 12,
};
const PHASE_OPTION_ACTIVE: CSSProperties = {
  ...PHASE_OPTION,
  color: "#ffffff",
  background: "var(--color-primary)",
};
const PROFILE_TITLE_GROUP: CSSProperties = {
  minWidth: 0,
  display: "flex",
  flexDirection: "column",
  gap: 1,
};
const PROFILE_GRID: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr 1fr",
  gap: 8,
  marginBottom: 8,
};
const CHANGE_GRID: CSSProperties = { ...PROFILE_GRID, marginBottom: 0 };
const KPI: CSSProperties = {
  minWidth: 0,
  padding: "7px 9px",
  borderRadius: 12,
  background: "var(--glass-chip)",
};
const KPI_LABEL: CSSProperties = {
  display: "block",
  color: "var(--glass-muted)",
  fontSize: 12,
  marginBottom: 2,
};
const KPI_VALUE: CSSProperties = {
  display: "block",
  color: "var(--glass-text)",
  fontWeight: 700,
  fontVariantNumeric: "tabular-nums",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};
const PROFILE_PRIMARY_GRID: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr 1fr",
  gap: 8,
  marginBottom: 10,
};
const PROFILE_BIG_METRIC: CSSProperties = {
  minWidth: 0,
  padding: "10px 12px",
  borderRadius: 14,
  background: "var(--glass-chip)",
  color: "var(--glass-muted)",
  display: "flex",
  flexDirection: "column",
  gap: 2,
};
const PROFILE_BIG_VALUE: CSSProperties = {
  color: "var(--glass-text)",
  fontSize: 20,
  lineHeight: 1.15,
  fontVariantNumeric: "tabular-nums",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};
const PROFILE_SPECIES_LIST: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 8,
  marginBottom: 8,
};
const PROFILE_SECTION: CSSProperties = {
  padding: 8,
  borderRadius: 14,
  background: "var(--glass-chip)",
};
const PROFILE_SECTION_TOTAL: CSSProperties = {
  ...PROFILE_SECTION,
  border: "1px solid var(--glass-border)",
  background: "var(--glass-bg-strong)",
};
const PROFILE_SECTION_HEAD: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  marginBottom: 6,
};
const PROFILE_SECTION_HEAD_TOTAL: CSSProperties = {
  ...PROFILE_SECTION_HEAD,
  marginBottom: 8,
};
const PROFILE_SECTION_TITLE: CSSProperties = {
  color: "var(--glass-text)",
  fontSize: 12,
  fontWeight: 750,
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};
const PROFILE_SECTION_TITLE_TOTAL: CSSProperties = {
  ...PROFILE_SECTION_TITLE,
  fontSize: 14,
  fontWeight: 850,
};
const PROFILE_QUAD_GRID: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
  gap: 5,
  marginBottom: 5,
};
const MINI_METRIC: CSSProperties = {
  minWidth: 0,
  padding: "6px 6px",
  borderRadius: 10,
  background: "rgba(255, 255, 255, 0.16)",
  color: "var(--glass-muted)",
  display: "flex",
  flexDirection: "column",
  gap: 1,
  fontSize: 10,
};
const MINI_METRIC_VALUE: CSSProperties = {
  color: "var(--glass-text)",
  fontSize: 11,
  fontWeight: 800,
  fontVariantNumeric: "tabular-nums",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};
const PROFILE_DIST_STACK: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr",
  gap: 5,
};
const PROFILE_DIST_ROW: CSSProperties = {
  minWidth: 0,
  display: "grid",
  gridTemplateColumns: "52px minmax(0, 1fr)",
  alignItems: "baseline",
  gap: 6,
  padding: "5px 7px",
  borderRadius: 10,
  color: "var(--glass-muted)",
  background: "rgba(255, 255, 255, 0.14)",
  fontSize: 11,
  fontVariantNumeric: "tabular-nums",
};
const PROFILE_DIST_VALUE: CSSProperties = {
  minWidth: 0,
  color: "var(--glass-text)",
  fontWeight: 750,
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};
const PROFILE_TAGS: CSSProperties = {
  display: "flex",
  gap: 5,
  flexWrap: "wrap",
};
const MINI_TAG: CSSProperties = {
  padding: "2px 7px",
  borderRadius: 999,
  color: "var(--glass-muted)",
  background: "var(--glass-chip)",
  fontSize: 11,
};
const OVERVIEW_KPI_GRID: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr 1fr",
  gap: 8,
};
const COMPACT_KPI: CSSProperties = {
  minWidth: 0,
  padding: "7px 9px",
  borderRadius: 12,
  background: "var(--glass-chip)",
  display: "flex",
  alignItems: "baseline",
  justifyContent: "space-between",
  gap: 8,
};
const COMPACT_LABEL: CSSProperties = {
  color: "var(--glass-muted)",
  fontSize: 11,
  whiteSpace: "nowrap",
};
const COMPACT_VALUE: CSSProperties = {
  color: "var(--glass-text)",
  fontSize: 15,
  fontWeight: 750,
  fontVariantNumeric: "tabular-nums",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};
const TRACT_TOOLS: CSSProperties = {
  ...GLASS,
  position: "absolute",
  left: 16,
  top: 64,
  zIndex: 8,
  width: 168,
  borderRadius: 16,
  padding: 8,
};
const SPECIES_GRID: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr",
  gap: 4,
};
const SPECIES_CHECK: CSSProperties = {
  marginInlineStart: 0,
  fontSize: 11,
  color: "var(--glass-text)",
};
const SPECIES_DOT: CSSProperties = {
  display: "inline-block",
  width: 9,
  height: 9,
  borderRadius: 3,
  marginRight: 5,
};
const MEASURE_READOUT: CSSProperties = {
  ...GLASS,
  position: "absolute",
  right: 64,
  top: 108,
  zIndex: 8,
  borderRadius: 16,
  padding: 10,
  minWidth: 150,
  display: "flex",
  flexDirection: "column",
  gap: 4,
};
const READOUT_MAIN: CSSProperties = {
  fontSize: 16,
  fontWeight: 700,
  color: "var(--glass-text)",
  fontVariantNumeric: "tabular-nums",
};
const READOUT_SUB: CSSProperties = { fontSize: 12, color: "var(--glass-muted)" };
const HOVER_CARD: CSSProperties = {
  ...GLASS,
  position: "fixed",
  transform: "translate(-50%, calc(-100% - 16px))",
  zIndex: 1000,
  pointerEvents: "none",
  width: 176,
  borderRadius: 16,
  padding: 10,
};
const HOVER_TITLE: CSSProperties = {
  fontWeight: 700,
  color: "var(--glass-text)",
  marginBottom: 6,
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};
const HOVER_ROW: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  fontSize: 12,
  lineHeight: "20px",
  color: "var(--glass-muted)",
  gap: 10,
};
const LOADING: CSSProperties = {
  ...GLASS,
  position: "absolute",
  left: "50%",
  top: "50%",
  transform: "translate(-50%, -50%)",
  zIndex: 9,
  borderRadius: 18,
  padding: 18,
};
const EMPTY: CSSProperties = {
  ...GLASS,
  position: "absolute",
  left: "50%",
  top: "50%",
  transform: "translate(-50%, -50%)",
  zIndex: 9,
  borderRadius: 18,
  padding: 24,
};
const STATUS_CHIP: CSSProperties = {
  ...GLASS,
  position: "absolute",
  left: "50%",
  bottom: 16,
  transform: "translateX(-50%)",
  zIndex: 8,
  borderRadius: 999,
  padding: "6px 12px",
  color: "var(--glass-text)",
  fontSize: 12,
};
