import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, MouseEvent as ReactMouseEvent, ReactNode } from "react";
import {
  Button,
  Checkbox,
  Empty,
  Popover,
  Select,
  Space,
  Spin,
  Tooltip,
  Tree,
  Typography,
} from "antd";
import type { DataNode } from "antd/es/tree";
import {
  BorderOutlined,
  CalendarOutlined,
  EyeInvisibleOutlined,
  EyeOutlined,
  LineChartOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  SearchOutlined,
  SwapOutlined,
} from "@ant-design/icons";
import { useNavigate, useParams } from "react-router-dom";
import { MapFloatingToolbar } from "../shared/ui/MapFloatingToolbar";
import { MapStage } from "../shared/ui/MapStage";
import {
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
import { endpoints, type DistributionSummary, type GeoPlace } from "../shared/api";
import { env } from "../shared/config/env";
import { formatAreaValue } from "../shared/lib/format";
import type { GeoFeature } from "../shared/api";
import { useObservations, type FeatureCollection } from "../entities/observation";
import {
  useTractImagery,
  useTractSummary,
  useTiffs,
  useTracts,
  type Tract,
  type TractSummary,
  type TiffAsset,
} from "../entities/tract";
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

interface TractGroup {
  key: string;
  label: string;
  tracts: Tract[];
  latest: Tract;
  center: LngLat;
}

interface HoveredTract {
  group: TractGroup;
  tiff?: TiffAsset;
  x: number;
  y: number;
}

export function MapWorkspacePage() {
  const {
    city: routeCity,
    county: routeCounty,
    tractId: routeTractId,
    phaseId: routePhaseId,
    tiffName,
  } = useParams();
  const navigate = useNavigate();
  const { data: tracts, error: tractsError, isError: tractsFailed, isLoading } = useTracts();
  const tiffsQuery = useTiffs();
  const [map, setMap] = useState<MapController | null>(null);
  const [ready, setReady] = useState(false);
  const [hovered, setHovered] = useState<HoveredTract | null>(null);
  const [selectedId, setSelectedId] = useState<string | undefined>(undefined);
  const [basemapId, setBasemapId] = useState(env.defaultBasemapId);
  const [roadVisible, setRoadVisible] = useState(false);
  const [showDetections, setShowDetections] = useState(true);
  const [selectedSpecies, setSelectedSpecies] = useState<string[]>([]);
  const [zoom, setZoom] = useState(env.overviewZoom);
  const [metersPerPixel, setMetersPerPixel] = useState(0);
  const [searchOpen, setSearchOpen] = useState(false);
  const [geoQuery, setGeoQuery] = useState("");
  const [geoPlaces, setGeoPlaces] = useState<GeoPlace[]>([]);
  const [geoSearching, setGeoSearching] = useState(false);
  const [measureMode, setMeasureMode] = useState<MeasureMode>("idle");
  const [measureCoords, setMeasureCoords] = useState<LngLat[]>([]);
  const [chromeHidden, setChromeHidden] = useState(false);
  const [checkedTiffKeys, setCheckedTiffKeys] = useState<string[]>([]);
  const [treeWidth, setTreeWidth] = useState(300);
  const detectionLayerIds = useRef<string[]>([]);
  const imageryLayerIds = useRef<string[]>([]);
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
  const tiffs = tiffsQuery.data ?? [];
  const tractGroups = useMemo(() => buildTractGroups(list), [list]);
  const overviewStats = useMemo(() => buildOverviewStats(list, tractGroups, tiffs), [list, tractGroups, tiffs]);
  const searchOptions = useMemo(() => buildSearchOptions(tractGroups, list, geoPlaces), [geoPlaces, list, tractGroups]);
  const groupByTract = useMemo(() => mapTractToGroup(tractGroups), [tractGroups]);
  const requestedCity = decodeParam(routeCity);
  const requestedCounty = decodeParam(routeCounty);
  const tractId = decodeParam(routeTractId);
  const requestedPhaseId = routePhaseId ?? undefined;
  const requestedTiffName = tiffName ? decodeURIComponent(tiffName) : undefined;
  const requestedSelectionId = useMemo(() => {
    if (!tractId) return undefined;
    if (requestedPhaseId) {
      const phase = list.find((t) =>
        sameAdmin(t, requestedCity, requestedCounty)
        && t.tract_id === tractId
        && t.phase_id === requestedPhaseId
      );
      if (phase) return tractRequestId(phase);
    }
    const direct = list.find((t) => tractRequestId(t) === tractId);
    if (direct) return tractRequestId(direct);
    const group = tractGroups.find((g) =>
      g.latest.tract_id === tractId && sameAdmin(g.latest, requestedCity, requestedCounty)
    );
    return group ? tractRequestId(group.latest) : tractId;
  }, [list, requestedCity, requestedCounty, requestedPhaseId, tractGroups, tractId]);
  const selected = useMemo(
    () => list.find((t) => tractRequestId(t) === selectedId),
    [list, selectedId],
  );
  const selectedGroup = selected ? groupByTract.get(tractRequestId(selected)) : undefined;
  const activeTract = selected;
  const activeTractId = activeTract ? tractRequestId(activeTract) : undefined;
  const validPathTiffs = useMemo(() => tiffs.filter((t) => t.path_exists), [tiffs]);
  const requestedTiff = useMemo(() => {
    if (!tractId || !requestedPhaseId || !requestedTiffName) return undefined;
    return tiffs.find(
      (t) =>
        sameAdmin(t, requestedCity, requestedCounty)
        &&
        t.tract_id === tractId
        && t.phase_id === requestedPhaseId
        && tiffRouteNameMatches(t, requestedTiffName),
    );
  }, [requestedCity, requestedCounty, requestedPhaseId, requestedTiffName, tiffs, tractId]);
  const isSingleImageView = Boolean(requestedTiffName);
  const phaseTiffs = useMemo(
    () =>
      validPathTiffs.filter(
        (t) =>
          sameAdmin(t, requestedCity, requestedCounty)
          && t.tract_id === tractId
          && t.phase_id === requestedPhaseId,
      ),
    [requestedCity, requestedCounty, requestedPhaseId, tractId, validPathTiffs],
  );
  const selectedPhaseTiffs = useMemo(() => {
    if (isSingleImageView) return requestedTiff ? [requestedTiff] : [];
    const checked = new Set(checkedTiffKeys);
    return phaseTiffs.filter((t) => checked.has(tiffKey(t)));
  }, [checkedTiffKeys, isSingleImageView, phaseTiffs, requestedTiff]);

  const observations = useObservations(activeTractId, "crown");
  const imagery = useTractImagery(isSingleImageView ? activeTractId : undefined, {
    phaseId: requestedTiff?.phase_id ?? requestedPhaseId,
    tiffName: requestedTiff?.file_name ?? requestedTiffName,
  });
  const summary = useTractSummary(activeTractId);
  const speciesList = useMemo(
    () => extractSpecies(observations.data),
    [observations.data],
  );
  const speciesColors = useMemo(
    () => buildSpeciesColorMap(speciesList),
    [speciesList],
  );

  const mappableTiffs = useMemo(() => validPathTiffs.filter(hasTiffCenter), [validPathTiffs]);
  const missingImageCoords = Math.max(0, validPathTiffs.length - mappableTiffs.length);

  useEffect(() => {
    if (!tractId || !requestedPhaseId || isSingleImageView) return;
    const preferred = phaseTiffs.find((t) => t.has_detection || t.observation_count > 0) ?? phaseTiffs[0];
    setCheckedTiffKeys(preferred ? [tiffKey(preferred)] : []);
  }, [isSingleImageView, phaseTiffs, requestedPhaseId, tractId]);

  useEffect(() => {
    if (!tractId) {
      if (selectedId) {
        setSelectedId(undefined);
        setMeasureMode("idle");
        setMeasureCoords([]);
        fittedTract.current = null;
        if (map && ready) {
          clearDetectionLayers(map, detectionLayerIds.current);
          detectionLayerIds.current = [];
          clearMeasureLayers(map);
          map.removeRasterOverlay(IMAGERY_LAYER);
          for (const id of imageryLayerIds.current) map.removeRasterOverlay(id);
          imageryLayerIds.current = [];
          map.fitBounds(overviewBounds, OVERVIEW_FIT);
        }
      }
      return;
    }
    if (requestedSelectionId && list.some((t) => tractRequestId(t) === requestedSelectionId)) {
      setSelectedId(requestedSelectionId);
    } else if (list.length > 0) {
      navigate("/map", { replace: true });
    }
  }, [tractId, requestedSelectionId, list, map, navigate, overviewBounds, ready, selectedId]);

  useEffect(() => {
    setSelectedSpecies(speciesList);
  }, [speciesList.join("|")]);

  useEffect(() => {
    const q = geoQuery.trim();
    if (!searchOpen || q.length < 2) {
      setGeoPlaces([]);
      setGeoSearching(false);
      return;
    }
    let cancelled = false;
    setGeoSearching(true);
    const timer = window.setTimeout(() => {
      endpoints.searchGeo(q, "广东", 12)
        .then((result) => {
          if (!cancelled) setGeoPlaces(result.places);
        })
        .catch(() => {
          if (!cancelled) setGeoPlaces([]);
        })
        .finally(() => {
          if (!cancelled) setGeoSearching(false);
        });
    }, 300);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [geoQuery, searchOpen]);

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
      setMetersPerPixel(metersPerScreenPixel(ctl.getCamera()));
    },
    [overviewBounds, overviewMaxBounds, syncMask],
  );

  useEffect(() => {
    if (!map || !ready) return;
    const off = map.on("move", () => {
      setZoom(map.getZoom());
      setMetersPerPixel(metersPerScreenPixel(map.getCamera()));
    });
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
    const markers: MarkerSpec[] = mappableTiffs.map((tiff) => {
      const group = tractGroups.find((g) => g.latest.tract_id === tiff.tract_id && sameAdmin(tiff, g.latest.city || undefined, g.latest.county || undefined));
      if (!group) return null;
      const element = createTractMarkerElement(Boolean(tiff.has_detection), {
        onClick: () => selectTiff(tiff),
        onEnter: (rect) =>
          setHovered({ group, tiff, x: rect.left + rect.width / 2, y: rect.top }),
        onLeave: () => setHovered(null),
      });
      return { id: `${tiff.phase_id}:${tiff.tiff_id}`, lngLat: [tiff.center_lng, tiff.center_lat] as LngLat, element };
    }).filter((item): item is MarkerSpec => Boolean(item));
    map.setMarkers(markers);
  }, [map, mappableTiffs, ready, selectedId, tractGroups]);

  useEffect(() => {
    if (!map || !ready) return;
    if (!isSingleImageView) {
      map.removeRasterOverlay(IMAGERY_LAYER);
      const nextIds = selectedPhaseTiffs
        .filter((tiff) => tiff.file_name)
        .map((tiff) => {
          const id = IMAGERY_LAYER + "-" + safeLayerId(tiffKey(tiff));
          map.setRasterOverlay(
            id,
            rasterBasemap([tiffTileUrl(tiff)], {
              tileSize: 256,
              minZoom: 12,
              maxZoom: 24,
            }),
          );
          return id;
        });
      for (const id of imageryLayerIds.current) {
        if (!nextIds.includes(id)) map.removeRasterOverlay(id);
      }
      imageryLayerIds.current = nextIds;
      return;
    }
    for (const id of imageryLayerIds.current) map.removeRasterOverlay(id);
    imageryLayerIds.current = [];
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
  }, [activeTract, imagery.data, isSingleImageView, map, ready, selectedPhaseTiffs]);

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
    const fitKey = requestedTiff ? `${activeTract.tract_id}:${requestedTiff.tiff_id}` : activeTract.tract_id;
    if (fittedTract.current === fitKey) return;
    fittedTract.current = fitKey;
    const tiffBounds = requestedTiff ? tiffFootprintBounds(requestedTiff) : null;
    if (tiffBounds) {
      map.fitBounds(tiffBounds, { padding: 88, maxZoom: 18, duration: 420 });
      return;
    }
    if (requestedTiff && hasTiffCenter(requestedTiff)) {
      map.flyTo([requestedTiff.center_lng, requestedTiff.center_lat], 16);
      return;
    }
    const b = boundsOf(observations.data as GeoJson);
    if (b) {
      map.fitBounds(b, 88);
      return;
    }
    const group = groupByTract.get(tractRequestId(activeTract));
    if (group) map.flyTo(group.center, 15);
  }, [activeTract, groupByTract, map, observations.data, ready, requestedTiff]);

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

  function selectGroup(group: TractGroup) {
    const id = tractRequestId(group.latest);
    setSelectedId(id);
    fittedTract.current = null;
    navigate(mapPhasePath(group.latest));
    map?.flyTo(group.center, 15);
  }

  function selectPhaseTract(tract: Tract) {
    const id = tractRequestId(tract);
    setSelectedId(id);
    fittedTract.current = null;
    navigate(mapPhasePath(tract));
  }

  function selectTiff(tiff: TiffAsset) {
    if (!tiff.file_name) {
      const group = tractGroups.find((g) => g.key === tiff.tract_id);
      if (group) selectGroup(group);
      return;
    }
    const phase = list.find((t) => t.tract_id === tiff.tract_id && t.phase_id === tiff.phase_id);
    const id = phase ? tractRequestId(phase) : tiff.tract_phase_pk;
    setSelectedId(id);
    fittedTract.current = null;
    navigate(mapTiffPath(tiff));
    if (hasTiffCenter(tiff)) map?.flyTo([tiff.center_lng, tiff.center_lat], 16);
  }

  function selectSearch(key: string) {
    const group = tractGroups.find((g) => g.key === key);
    if (group) {
      selectGroup(group);
      return;
    }
    const place = geoPlaces.find((p) => "geo:" + p.id === key);
    if (place) {
      setSelectedId(undefined);
      fittedTract.current = null;
      navigate("/map");
      map?.flyTo([place.lng, place.lat], 13);
      return;
    }
    if (key.startsWith("admin:")) {
      const [, level, name] = key.split(":");
      const match = tractGroups.find((g) =>
        g.tracts.some((t) => {
          if (level === "city") return t.city === name;
          if (level === "county") return t.county === name;
          return t.town === name;
        }),
      );
      if (match) selectGroup(match);
    }
  }

  function resetNorth() {
    if (!map) return;
    map.jumpTo({ ...map.getCamera(), bearing: 0, pitch: 0 });
  }

  function returnOverview() {
    navigate("/map");
    setSelectedId(undefined);
    setMeasureMode("idle");
    setMeasureCoords([]);
    fittedTract.current = null;
    if (map) {
      clearDetectionLayers(map, detectionLayerIds.current);
      detectionLayerIds.current = [];
      clearMeasureLayers(map);
      map.removeRasterOverlay(IMAGERY_LAYER);
      for (const id of imageryLayerIds.current) map.removeRasterOverlay(id);
      imageryLayerIds.current = [];
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
            filterOption={false}
            onSearch={setGeoQuery}
            loading={geoSearching}
            notFoundContent={geoSearching ? <Spin size="small" /> : "无结果"}
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
            opacity: selectedGroup.tracts.length < 2 ? 0.54 : 1,
          }}
          disabled={selectedGroup.tracts.length < 2}
          onClick={() => navigate(`/change?tract_id=${encodeURIComponent(selectedGroup.latest.tract_id)}`)}
        >
          <SwapOutlined />
          <span>时相对比</span>
        </button>
      ) : null}

      {!chromeHidden ? (
        <MapFloatingToolbar
          basemapId={basemapId}
          onBasemapChange={setBasemapId}
          roadVisible={roadVisible}
          onRoadVisibleChange={setRoadVisible}
          pixelSizeLabel={formatPixelSize(metersPerPixel)}
          zoomLabel={zoom.toFixed(1)}
          homeTitle="回到总观视野"
          onZoomIn={() => map?.zoomIn()}
          onZoomOut={() => map?.zoomOut()}
          onHome={returnOverview}
          onResetNorth={resetNorth}
          extraActions={
            <>
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
            </>
          }
        />
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
        <ProfilePanel
          tract={activeTract}
          group={selectedGroup}
          imagery={imagery.data}
          summary={summary.data}
          phaseTiffs={phaseTiffs}
          speciesColors={speciesColors}
          onSelectPhase={selectPhaseTract}
          loading={observations.isFetching || imagery.isFetching || summary.isFetching}
        />
      ) : null}

      {!chromeHidden && selectedGroup && activeTract && !isSingleImageView ? (
        <TiffTreePanel
          group={selectedGroup}
          tiffs={validPathTiffs.filter((t) =>
            sameAdmin(t, requestedCity, requestedCounty) && t.tract_id === tractId
          )}
          activePhaseId={requestedPhaseId ?? activeTract.phase_id}
          checkedKeys={checkedTiffKeys}
          width={treeWidth}
          onWidthChange={setTreeWidth}
          onSelectPhase={selectPhaseTract}
          onCheckedKeysChange={setCheckedTiffKeys}
        />
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

      {!chromeHidden && hovered ? <TractHoverCard hovered={hovered} /> : null}

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
      ) : tractGroups.length === 0 ? (
        <div style={EMPTY}>
          <Empty description="暂无可上图地块" />
        </div>
      ) : null}

      {!chromeHidden && missingImageCoords > 0 ? (
        <div style={STATUS_CHIP}>{missingImageCoords} 个有效影像缺少 footprint 中心点</div>
      ) : null}
    </div>
  );
}

function buildTractGroups(tracts: Tract[]): TractGroup[] {
  const byKey = new Map<string, Tract[]>();
  for (const tract of tracts) {
    const key = tractGroupKey(tract);
    const arr = byKey.get(key) ?? [];
    arr.push(tract);
    byKey.set(key, arr);
  }
  const groups: TractGroup[] = [];
  for (const [key, arr] of byKey) {
    const sorted = [...arr].sort(compareTractTime);
    const latest = sorted[sorted.length - 1];
    const centerSource = [...sorted].reverse().find((t) => tractCenter(t));
    const center = centerSource ? tractCenter(centerSource) : null;
    if (!center) continue;
    groups.push({
      key,
      label: latest.tract_id,
      tracts: sorted,
      latest,
      center,
    });
  }
  groups.sort((a, b) => a.label.localeCompare(b.label, "zh-Hans-CN"));
  return groups;
}

function mapTractToGroup(groups: TractGroup[]): Map<string, TractGroup> {
  const out = new Map<string, TractGroup>();
  for (const group of groups) {
    out.set(group.key, group);
    for (const tract of group.tracts) out.set(tractRequestId(tract), group);
  }
  return out;
}

function tractRequestId(tract: Tract): string {
  return String(tract.tract_phase_pk || tract.tract_id);
}

function tractGroupKey(tract: Pick<Tract, "city" | "county" | "tract_id">): string {
  return [tract.city || "", tract.county || "", tract.tract_id].join("\u0000");
}

function decodeParam(value?: string): string | undefined {
  return value ? decodeURIComponent(value) : undefined;
}

function sameAdmin(
  item: { city?: string | null; county?: string | null },
  city?: string,
  county?: string,
): boolean {
  return (!city || item.city === city) && (!county || item.county === county);
}

function mapPhasePath(tract: Tract): string {
  return [
    "/map",
    encodeURIComponent(tract.city || "未知市"),
    encodeURIComponent(tract.county || "未知县"),
    encodeURIComponent(tract.tract_id),
    encodeURIComponent(tract.phase_id || "00000000"),
  ].join("/");
}

function mapTiffPath(tiff: TiffAsset): string {
  return [
    "/map",
    encodeURIComponent(tiff.city || "未知市"),
    encodeURIComponent(tiff.county || "未知县"),
    encodeURIComponent(tiff.tract_id),
    encodeURIComponent(tiff.phase_id),
    encodeURIComponent(tiff.file_name || tiff.tiff_id),
  ].join("/");
}

function tiffKey(tiff: Pick<TiffAsset, "phase_id" | "tiff_id" | "file_name">): string {
  return `${tiff.phase_id}:${tiff.tiff_id}:${tiff.file_name || ""}`;
}

function tiffRouteNameMatches(tiff: Pick<TiffAsset, "file_name" | "tiff_id">, routeName?: string): boolean {
  if (!routeName) return false;
  const fileName = tiff.file_name || "";
  return routeName === fileName || routeName === stripTiffSuffix(fileName) || routeName === tiff.tiff_id;
}

function stripTiffSuffix(value: string): string {
  return value.replace(/\.(tif|tiff)$/i, "");
}

function phaseNodeKey(phaseId: string): string {
  return "phase:" + phaseId;
}

function tiffTileUrl(tiff: TiffAsset): string {
  return `/api/v1/tiles/tiffs/${encodeURIComponent(tiff.phase_id)}/${encodeURIComponent(tiff.file_name || tiff.tiff_id)}/{z}/{x}/{y}`;
}

function buildSearchOptions(groups: TractGroup[], tracts: Tract[], places: GeoPlace[]) {
  const adminOptions = [
    ...unique(tracts.map((t) => t.city)).map((name) => ({ value: "admin:city:" + name, label: name })),
    ...unique(tracts.map((t) => t.county)).map((name) => ({ value: "admin:county:" + name, label: name })),
    ...unique(tracts.map((t) => t.town)).map((name) => ({ value: "admin:town:" + name, label: name })),
  ];
  return [
    {
      label: "地名",
      options: places.map((p) => ({
        value: "geo:" + p.id,
        label: p.address ? `${p.name} · ${p.address}` : p.name,
      })),
    },
    {
      label: "地块",
      options: groups.map((g) => ({ value: g.key, label: g.label })),
    },
    {
      label: "行政区划",
      options: adminOptions,
    },
  ];
}

function unique(values: Array<string | null | undefined>): string[] {
  return [...new Set(values.filter((v): v is string => Boolean(v)))].sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
}

function buildOverviewStats(tracts: Tract[], groups: TractGroup[], tiffs: TiffAsset[]) {
  const trackedProjects = new Set(tiffs.map((t) => t.tract_id)).size || groups.length;
  const trackedPhases = new Set(tiffs.map((t) => `${t.tract_id}:${t.phase_id}`)).size || tracts.length;
  const validTiffs = tiffs.filter((t) => t.path_exists);
  const detectedTiffs = tiffs.filter((t) => t.has_detection || t.observation_count > 0);
  const detectedProjects = new Set(detectedTiffs.map((t) => t.tract_id)).size;
  const detectedPhases = new Set(detectedTiffs.map((t) => `${t.tract_id}:${t.phase_id}`)).size;
  const area = detectedTiffs.reduce((sum, t) => sum + (t.geo_area ?? 0), 0);
  const trees = detectedTiffs.reduce((sum, t) => sum + (t.observation_count ?? 0), 0);
  return {
    trackedProjects,
    trackedImages: tiffs.length,
    validImages: validTiffs.length,
    trackedPhases,
    detectedProjects,
    detectedImages: detectedTiffs.length,
    detectedPhases,
    area,
    trees,
    pendingImages: Math.max(0, validTiffs.length - detectedTiffs.length),
  };
}

function hasTiffCenter(tiff: TiffAsset): tiff is TiffAsset & { center_lng: number; center_lat: number } {
  return typeof tiff.center_lng === "number" && typeof tiff.center_lat === "number";
}

function tiffFootprintBounds(tiff: TiffAsset): BBox | null {
  const raw = tiff.footprint_bbox;
  if (typeof raw !== "string" || !raw.trim()) return null;
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed) || parsed.length !== 4) return null;
    const [west, south, east, north] = parsed.map(Number);
    if (![west, south, east, north].every(Number.isFinite)) return null;
    if (west >= east || south >= north) return null;
    return [[west, south], [east, north]];
  } catch {
    return null;
  }
}

function compareTractTime(a: Tract, b: Tract): number {
  return String(a.phase_id || "").localeCompare(String(b.phase_id || ""));
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
      <div style={OVERVIEW_SECTION_STACK}>
        <OverviewSection title="已跟踪项目">
          <CompactKpi label="项目数" value={String(stats.trackedProjects)} />
          <CompactKpi label="影像数" value={String(stats.trackedImages)} />
          <CompactKpi label="有效影像" value={String(stats.validImages)} />
          <CompactKpi label="时相数" value={String(stats.trackedPhases)} />
        </OverviewSection>
        <OverviewSection title="已检测项目">
          <CompactKpi label="项目数" value={String(stats.detectedProjects)} />
          <CompactKpi label="影像数" value={String(stats.detectedImages)} />
          <CompactKpi label="时相数" value={String(stats.detectedPhases)} />
          <CompactKpi label="待检测" value={String(stats.pendingImages)} />
          <CompactKpi label="总株数" value={stats.trees.toLocaleString()} wide />
          <CompactKpi label="总面积" value={formatAreaValue(stats.area)} wide />
        </OverviewSection>
      </div>
    </div>
  );
}

function OverviewSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={OVERVIEW_SECTION}>
      <div style={OVERVIEW_SECTION_TITLE}>{title}</div>
      <div style={OVERVIEW_KPI_GRID}>{children}</div>
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

function TiffTreePanel({
  group,
  tiffs,
  activePhaseId,
  checkedKeys,
  width,
  onWidthChange,
  onSelectPhase,
  onCheckedKeysChange,
}: {
  group: TractGroup;
  tiffs: TiffAsset[];
  activePhaseId?: string;
  checkedKeys: string[];
  width: number;
  onWidthChange: (width: number) => void;
  onSelectPhase: (tract: Tract) => void;
  onCheckedKeysChange: (keys: string[]) => void;
}) {
  const phaseMap = useMemo(() => {
    const out = new Map<string, TiffAsset[]>();
    for (const tiff of tiffs) {
      const key = tiff.phase_id || "未知时相";
      const arr = out.get(key) ?? [];
      arr.push(tiff);
      out.set(key, arr);
    }
    return out;
  }, [tiffs]);

  const treeData = useMemo<DataNode[]>(() =>
    group.tracts.map((phase) => {
      const phaseKey = phase.phase_id || "未知时相";
      const active = phase.phase_id === activePhaseId;
      const children = (phaseMap.get(phaseKey) ?? []).map((tiff) => ({
        key: tiffKey(tiff),
        title: (
          <span style={active ? TREE_LEAF_TITLE : TREE_MUTED_TITLE}>
            {tiff.file_name || tiff.tiff_id}
            <Text type="secondary"> · {(tiff.observation_count ?? 0).toLocaleString()} 株</Text>
          </span>
        ),
        disabled: !active,
      }));
      return {
        key: phaseNodeKey(phaseKey),
        title: (
          <button
            type="button"
            style={active ? TREE_PHASE_ACTIVE : TREE_PHASE_MUTED}
            onClick={() => onSelectPhase(phase)}
          >
            <span>{phaseKey}</span>
            <strong>{children.length} 图</strong>
          </button>
        ),
        disabled: !active,
        selectable: false,
        children,
      };
    }),
  [activePhaseId, group.tracts, onSelectPhase, phaseMap]);

  function startResize(e: ReactMouseEvent<HTMLDivElement>) {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = width;
    const move = (event: MouseEvent) => {
      onWidthChange(clamp(startWidth + startX - event.clientX, 260, 520));
    };
    const up = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  }

  return (
    <div style={{ ...TIFF_TREE_PANEL, width }}>
      <div style={RESIZE_HANDLE} onMouseDown={startResize} />
      <div style={PANEL_HEAD}>
        <span style={PANEL_TITLE}>影像文件</span>
        <span style={PANEL_SUBTITLE}>{activePhaseId || "未知时相"}</span>
      </div>
      <Tree
        checkable
        selectable={false}
        blockNode
        checkedKeys={checkedKeys}
        expandedKeys={activePhaseId ? [phaseNodeKey(activePhaseId)] : []}
        treeData={treeData}
        onCheck={(keys) => {
          const next = (Array.isArray(keys) ? keys : keys.checked)
            .map(String)
            .filter((key) => !key.startsWith("phase:"));
          onCheckedKeysChange(next);
        }}
      />
    </div>
  );
}

function ProfilePanel({
  tract,
  group,
  imagery,
  summary,
  phaseTiffs,
  speciesColors,
  onSelectPhase,
  loading,
}: {
  tract: Tract;
  group: TractGroup;
  imagery?: { available: boolean; source_format?: string | null; tile_service?: string | null };
  summary?: TractSummary;
  phaseTiffs?: TiffAsset[];
  speciesColors: Map<string, string>;
  onSelectPhase: (tract: Tract) => void;
  loading: boolean;
}) {
  const meta = summary?.meta;
  const metricSections = buildProfileMetricSections(summary, tract, speciesColors);
  const detectedTiffs = (phaseTiffs ?? []).filter((t) => t.has_detection || t.observation_count > 0);
  return (
    <div style={PROFILE_PANEL}>
      <div style={PANEL_HEAD}>
        <div style={PROFILE_TITLE_GROUP}>
          <span style={PANEL_TITLE}>{tract.tract_id}</span>
          <span style={PANEL_SUBTITLE}>时相ID {tract.phase_id || "未知时相"}</span>
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
                    key={tractRequestId(phase)}
                    type="button"
                    style={tractRequestId(phase) === tractRequestId(tract) ? PHASE_OPTION_ACTIVE : PHASE_OPTION}
                    onClick={() => onSelectPhase(phase)}
                  >
                    <span>{phase.phase_id || "未知时相"}</span>
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
        {phaseTiffs ? <span style={MINI_TAG}>{detectedTiffs.length}/{phaseTiffs.length} 图已检测</span> : null}
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
    crownW: summary?.crown_width_geo,
    crownH: summary?.crown_height_geo,
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
    crownW: item.crown_width_geo,
    crownH: item.crown_height_geo,
        crownAreaDist: item.crown_area_geo,
        height: item.height,
      } satisfies ProfileMetricSectionData;
    });
  return species.length <= 1 ? species : [total, ...species];
}

function TractHoverCard({ hovered }: { hovered: HoveredTract }) {
  const { group, tiff, x, y } = hovered;
  const style: CSSProperties = { ...HOVER_CARD, left: x, top: y };
  if (tiff) {
    return (
      <div style={style}>
        <div style={HOVER_TITLE}>{tiff.file_name || tiff.tiff_id}</div>
        <div style={HOVER_ROW}>
          <span>地块</span>
          <strong>{tiff.tract_id}</strong>
        </div>
        <div style={HOVER_ROW}>
          <span>时相</span>
          <strong>{tiff.phase_id || "-"}</strong>
        </div>
        <div style={HOVER_ROW}>
          <span>状态</span>
          <strong style={tiff.has_detection ? HOVER_OK : HOVER_WARN}>{tiff.status}</strong>
        </div>
        <div style={HOVER_ROW}>
          <span>株数</span>
          <strong>{(tiff.observation_count ?? 0).toLocaleString()}</strong>
        </div>
        <div style={HOVER_ROW}>
          <span>面积</span>
          <strong>{formatAreaValue(tiff.geo_area ?? 0)}</strong>
        </div>
      </div>
    );
  }
  return (
    <div style={style}>
      <div style={HOVER_TITLE}>{group.label}</div>
      <div style={HOVER_ROW}>
        <span>最新时相</span>
        <strong>{group.latest.phase_id || "-"}</strong>
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

function formatTractArea(tract: Tract): string {
  if (typeof tract.geo_area !== "number") return "-";
  return formatAreaValue(tract.geo_area);
}

function formatDensity(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return value.toLocaleString(undefined, { maximumFractionDigits: 1 }) + " 株/hm\u00b2";
}

function metersPerScreenPixel(camera: { center: LngLat; zoom: number }): number {
  const lat = Math.max(-85.05112878, Math.min(85.05112878, camera.center[1]));
  return (156543.03392804097 * Math.cos((lat * Math.PI) / 180)) / 2 ** camera.zoom;
}

function formatPixelSize(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "-";
  if (value >= 100) return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (value >= 1) return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (value >= 0.01) return value.toLocaleString(undefined, { maximumFractionDigits: 3 });
  return value.toExponential(2);
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
  width: 312,
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
  gap: 6,
};
const OVERVIEW_SECTION_STACK: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 8,
};
const OVERVIEW_SECTION: CSSProperties = {
  padding: 8,
  borderRadius: 14,
  background: "var(--glass-chip)",
};
const OVERVIEW_SECTION_TITLE: CSSProperties = {
  marginBottom: 7,
  color: "var(--glass-text)",
  fontSize: 12,
  fontWeight: 800,
};
const COMPACT_KPI: CSSProperties = {
  minWidth: 0,
  padding: "7px 8px",
  borderRadius: 12,
  background: "rgba(255, 255, 255, 0.14)",
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
const TIFF_TREE_PANEL: CSSProperties = {
  ...GLASS,
  position: "absolute",
  right: 16,
  top: "50%",
  transform: "translateY(-50%)",
  zIndex: 8,
  maxHeight: "min(62vh, 620px)",
  overflowY: "auto",
  borderRadius: 16,
  padding: 12,
  color: "var(--glass-text)",
};
const RESIZE_HANDLE: CSSProperties = {
  position: "absolute",
  left: 0,
  top: 10,
  bottom: 10,
  width: 6,
  cursor: "ew-resize",
  borderRadius: 999,
  background: "rgba(255, 255, 255, 0.16)",
};
const TREE_PHASE_ACTIVE: CSSProperties = {
  width: "100%",
  border: 0,
  background: "transparent",
  color: "var(--glass-text)",
  display: "flex",
  justifyContent: "space-between",
  gap: 8,
  padding: 0,
  cursor: "pointer",
};
const TREE_PHASE_MUTED: CSSProperties = {
  ...TREE_PHASE_ACTIVE,
  color: "var(--glass-muted)",
  opacity: 0.48,
};
const TREE_LEAF_TITLE: CSSProperties = { color: "var(--glass-text)" };
const TREE_MUTED_TITLE: CSSProperties = { color: "var(--glass-muted)", opacity: 0.46 };
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
const HOVER_OK: CSSProperties = {
  color: "#9ff0c4",
};
const HOVER_WARN: CSSProperties = {
  color: "#ffd166",
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
