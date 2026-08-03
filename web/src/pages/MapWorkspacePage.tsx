import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  Typography,
} from "antd";
import {
  BorderOutlined,
  CalendarOutlined,
  EditOutlined,
  EyeInvisibleOutlined,
  EyeOutlined,
  LineChartOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  SearchOutlined,
  SwapOutlined,
} from "@ant-design/icons";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { geometryBbox } from "../features/effective-area-editor/geometryOperations";
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
import { buildInvalidAreaMask, formatHm2, useEffectiveArea } from "../entities/effective-area";
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
const EFFECTIVE_MASK = "effective-area-mask";
const EFFECTIVE_LINE = "effective-area-line";
const LazyEffectiveAreaEditor = lazy(() =>
  import("../features/effective-area-editor/EffectiveAreaEditor").then((module) => ({ default: module.EffectiveAreaEditor })),
);
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
  "#3a86c8",
  "#8338ec",
  "#ff006e",
  "#e05300",
  "#0077b6",
  "#5c677d",
  "#a90011",
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
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: tracts, error: tractsError, isError: tractsFailed, isLoading } = useTracts();
  const tiffsQuery = useTiffs();
  const [map, setMap] = useState<MapController | null>(null);
  const [ready, setReady] = useState(false);
  const [hovered, setHovered] = useState<HoveredTract | null>(null);
  const [selectedId, setSelectedId] = useState<string | undefined>(undefined);
  const [basemapId, setBasemapId] = useState(env.defaultBasemapId);
  const [roadVisible, setRoadVisible] = useState(false);
  const [showDetections, setShowDetections] = useState(true);
  const [showEffectiveArea, setShowEffectiveArea] = useState(false);
  const [effectiveMode, setEffectiveMode] = useState<"outline" | "mask">("outline");
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
  const [singlePhaseMarkers, setSinglePhaseMarkers] = useState(true);
  const [checkedTiffKeys, setCheckedTiffKeys] = useState<string[]>([]);
  const [treeWidth, setTreeWidth] = useState(240);
  const [profileWidth, setProfileWidth] = useState(420);
  const detectionLayerIds = useRef<string[]>([]);
  const imageryLayerIds = useRef<string[]>([]);
  const fittedTract = useRef<string | null>(null);
  const preheatTimer = useRef<number | null>(null);

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
  const preheatTiffRef = requestedTiff?.tiff_id;
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
  const editorImageryTiles = useMemo(
    () => phaseTiffs.filter((tiff) => tiff.file_name).map(tiffTileUrl),
    [phaseTiffs],
  );

  const observations = useObservations(activeTractId, "crown");
  const visibleObservations = useMemo(() => {
    const data = observations.data;
    if (!data) return undefined;
    if (isSingleImageView && requestedTiff) return filterObservationsByTiffs(data, [requestedTiff.tiff_id]);
    if (!isSingleImageView && selectedPhaseTiffs.length > 0) {
      return filterObservationsByTiffs(data, selectedPhaseTiffs.map((tiff) => tiff.tiff_id));
    }
    return data;
  }, [isSingleImageView, observations.data, requestedTiff, selectedPhaseTiffs]);
  const activeAreaHm2 = useMemo(() => {
    if (isSingleImageView && requestedTiff) {
      const eff = requestedTiff.effective_area_hm2 ?? requestedTiff.area_hm2;
      if (typeof eff === "number" && eff > 0) return eff;
      if (typeof requestedTiff.geo_area === "number" && requestedTiff.geo_area > 0) {
        return requestedTiff.geo_area > 1000 ? requestedTiff.geo_area / 10000 : requestedTiff.geo_area;
      }
    }
    if (activeTract) {
      const effTract = activeTract.effective_area_hm2 ?? activeTract.tract_phase_area_hm2 ?? activeTract.tract_area_hm2;
      if (typeof effTract === "number" && effTract > 0) return effTract;
      if (typeof activeTract.geo_area === "number" && activeTract.geo_area > 0) {
        return activeTract.geo_area > 1000 ? activeTract.geo_area / 10000 : activeTract.geo_area;
      }
    }
    return undefined;
  }, [activeTract, isSingleImageView, requestedTiff]);

  const activeAreaM2 = useMemo(() => {
    return activeAreaHm2 !== undefined ? activeAreaHm2 * 10000 : undefined;
  }, [activeAreaHm2]);

  const visibleSummary = useMemo(
    () =>
      visibleObservations
        ? summaryFromObservations(
          visibleObservations,
          activeAreaM2,
        )
        : undefined,
    [activeAreaM2, visibleObservations],
  );
  const imagery = useTractImagery(isSingleImageView ? activeTractId : undefined, {
    phaseId: requestedTiff?.phase_id ?? requestedPhaseId,
    tiffName: requestedTiff?.file_name ?? requestedTiffName,
  });
  const summary = useTractSummary(activeTractId);
  const effectiveArea = useEffectiveArea(activeTract?.tract_pk);
  const editingEffectiveArea = searchParams.get("effective-area");
  const speciesList = useMemo(
    () => extractSpecies(visibleObservations),
    [visibleObservations],
  );
  const speciesColors = useMemo(
    () => buildSpeciesColorMap(speciesList),
    [speciesList],
  );

  const mappableTiffs = useMemo(() => validPathTiffs.filter(hasTiffCenter), [validPathTiffs]);
  const overviewMarkerTiffs = useMemo(() => {
    if (!singlePhaseMarkers) return mappableTiffs;
    const latestPhaseByGroup = new Map(
      tractGroups.map((group) => [group.key, group.latest.phase_id]),
    );
    return mappableTiffs.filter(
      (tiff) => latestPhaseByGroup.get(tractGroupKey(tiff)) === tiff.phase_id,
    );
  }, [mappableTiffs, singlePhaseMarkers, tractGroups]);
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

  const scheduleTiffPreheat = useCallback(() => {
    if (!map || !ready || !isSingleImageView || !requestedPhaseId || !preheatTiffRef || observations.isFetching) return;
    if (preheatTimer.current) window.clearTimeout(preheatTimer.current);
    preheatTimer.current = window.setTimeout(() => {
      const bounds = map.getBounds();
      const currentZoom = map.getZoom();
      void endpoints.preheatTiffTiles(requestedPhaseId, preheatTiffRef, {
        bounds,
        zoom: currentZoom,
        include_adjacent_zooms: true,
      }).catch(() => undefined);
    }, 900);
  }, [isSingleImageView, map, observations.isFetching, preheatTiffRef, ready, requestedPhaseId]);

  useEffect(() => {
    if (!map || !ready || !isSingleImageView) return;
    scheduleTiffPreheat();
    const off = map.on("moveend", scheduleTiffPreheat);
    return () => {
      off();
      if (preheatTimer.current) {
        window.clearTimeout(preheatTimer.current);
        preheatTimer.current = null;
      }
    };
  }, [isSingleImageView, map, ready, scheduleTiffPreheat]);

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
    const markers: MarkerSpec[] = overviewMarkerTiffs.map((tiff) => {
      const group = tractGroups.find((g) => g.latest.tract_id === tiff.tract_id && sameAdmin(tiff, g.latest.city || undefined, g.latest.county || undefined));
      if (!group) return null;
      const element = createTractMarkerElement(
        Boolean(tiff.has_detection),
        {
          onClick: () => selectTiff(tiff),
          onEnter: (rect) =>
            setHovered({ group, tiff, x: rect.left + rect.width / 2, y: rect.top }),
          onLeave: () => setHovered(null),
        },
        outlineColorForTract(tiff),
      );
      return { id: `${tiff.phase_id}:${tiff.tiff_id}`, lngLat: [tiff.center_lng, tiff.center_lat] as LngLat, element };
    }).filter((item): item is MarkerSpec => Boolean(item));
    map.setMarkers(spreadNearbyMarkers(markers, map.getZoom()));
  }, [map, overviewMarkerTiffs, ready, selectedId, tractGroups, zoom]);

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
              maxZoom: 25,
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
    if (requestedTiff) {
      map.setRasterOverlay(
        IMAGERY_LAYER,
        rasterBasemap([tiffTileUrl(requestedTiff)], {
          tileSize: 256,
          minZoom: 12,
          maxZoom: 25,
        }),
      );
    } else if (activeTract && imagery.data?.available && imagery.data.tiles?.length) {
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
  }, [activeTract, imagery.data, isSingleImageView, map, ready, requestedTiff, selectedPhaseTiffs]);

  useEffect(() => {
    if (!map || !ready) return;
    clearDetectionLayers(map, detectionLayerIds.current);
    detectionLayerIds.current = [];
    if (!showDetections || !visibleObservations) return;
    if (speciesList.length > 0 && selectedSpecies.length === 0) return;
    const layers = buildSpeciesLayers(visibleObservations, selectedSpecies, speciesColors);
    for (const layer of layers) {
      map.setGeoJsonLayer(layer);
      detectionLayerIds.current.push(layer.id);
    }
  }, [map, ready, selectedSpecies, showDetections, speciesColors, speciesList.length, visibleObservations]);

  useEffect(() => {
    if (!map || !ready) return;
    map.removeLayer(EFFECTIVE_MASK);
    map.removeLayer(EFFECTIVE_LINE);
    if (!showEffectiveArea || !effectiveArea.data) return;

    if (effectiveMode === "mask") {
      map.setGeoJsonLayer({
        id: EFFECTIVE_MASK,
        kind: "polygon",
        data: buildInvalidAreaMask(effectiveArea.data.boundary_geometry, effectiveArea.data.geometry),
        color: "#24171a",
        opacity: 0.55,
      });
    }

    if (effectiveMode === "outline") {
      const geomToDraw = effectiveArea.data.geometry;
      map.setGeoJsonLayer({
        id: EFFECTIVE_LINE,
        kind: "line",
        data: { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: geomToDraw }] },
        color: "#ff7a00",
        opacity: 0.95,
        lineWidth: 2.2,
      });
    }
  }, [effectiveArea.data, effectiveMode, map, ready, showEffectiveArea]);

  useEffect(() => {
    if (!map || !ready || !activeTract || !visibleObservations) return;
    const fitKey = requestedTiff ? `${activeTract.tract_id}:${requestedTiff.tiff_id}` : activeTract.tract_id;
    if (fittedTract.current === fitKey) return;
    fittedTract.current = fitKey;

    if (requestedTiff) {
      const tiffBounds = tiffFootprintBounds(requestedTiff);
      if (tiffBounds) {
        map.fitBounds(tiffBounds, { padding: 88, maxZoom: 18, duration: 420 });
        return;
      }
      if (hasTiffCenter(requestedTiff)) {
        map.flyTo([requestedTiff.center_lng, requestedTiff.center_lat], 16);
        return;
      }
    } else {
      if (effectiveArea.data?.boundary_geometry) {
        const [west, south, east, north] = geometryBbox(effectiveArea.data.boundary_geometry);
        map.fitBounds([[west, south], [east, north]], { padding: 88, maxZoom: 18, duration: 420 });
        return;
      }
    }

    const b = boundsOf(visibleObservations as GeoJson);
    if (b) {
      map.fitBounds(b, 88);
      return;
    }
    const group = groupByTract.get(tractRequestId(activeTract));
    if (group) map.flyTo(group.center, 15);
  }, [activeTract, effectiveArea.data?.boundary_geometry, groupByTract, map, ready, requestedTiff, visibleObservations]);

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
      ) : (
        <div style={TOP_LEFT_TOOLS}>
          {searchOpen ? (
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
          {!selectedGroup ? (
            <button
              type="button"
              aria-pressed={singlePhaseMarkers}
              onClick={() => setSinglePhaseMarkers((value) => !value)}
              style={singlePhaseMarkers ? SINGLE_PHASE_BUTTON_ACTIVE : SINGLE_PHASE_BUTTON}
            >
              单时相
            </button>
          ) : null}
        </div>
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
          homeTitle="返回总览"
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
                title="隐藏面板"
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
          summary={visibleSummary ?? summary.data}
          phaseTiffs={phaseTiffs}
          speciesColors={speciesColors}
          onSelectPhase={selectPhaseTract}
          loading={observations.isFetching || imagery.isFetching || summary.isFetching}
          tiffName={requestedTiffName}
          isSingleImageView={isSingleImageView}
          requestedTiff={requestedTiff}
          width={profileWidth}
          onWidthChange={setProfileWidth}
        />
      ) : null}

      {!chromeHidden && selectedGroup && activeTract && !isSingleImageView ? (
        <TiffTreePanel
          tiffs={phaseTiffs}
          activePhaseId={requestedPhaseId ?? activeTract.phase_id}
          checkedKeys={checkedTiffKeys}
          width={treeWidth}
          onWidthChange={setTreeWidth}
          onCheckedKeysChange={setCheckedTiffKeys}
        />
      ) : null}

      {!chromeHidden && !selectedGroup ? <OverviewProfileCard stats={overviewStats} /> : null}

      {!chromeHidden && selectedGroup && activeTract ? (
        <div style={TRACT_TOOLS}>
          <Space direction="vertical" size={10} style={FULL}>
            <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
              <Button
                size="small"
                type={showEffectiveArea ? "primary" : "default"}
                icon={showEffectiveArea ? <EyeOutlined /> : <EyeInvisibleOutlined />}
                onClick={() => setShowEffectiveArea((v) => !v)}
              >
                显示有效区
              </Button>
              {showEffectiveArea ? (
                <Space size={4} style={{ display: "inline-flex" }}>
                  <Button
                    size="small"
                    type={effectiveMode === "outline" ? "primary" : "default"}
                    onClick={() => setEffectiveMode("outline")}
                  >
                    框线模式
                  </Button>
                  <Button
                    size="small"
                    type={effectiveMode === "mask" ? "primary" : "default"}
                    onClick={() => setEffectiveMode("mask")}
                  >
                    遮罩模式
                  </Button>
                </Space>
              ) : null}
              <Button
                size="small"
                type="default"
                icon={<EditOutlined />}
                onClick={() => {
                  if (!activeTract.tract_pk) return;
                  const next = new URLSearchParams(searchParams);
                  next.set("effective-area", activeTract.tract_pk);
                  setSearchParams(next);
                }}
              >
                编辑有效区
              </Button>
            </div>
            <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
              <Button
                size="small"
                type={showDetections ? "primary" : "default"}
                icon={showDetections ? <EyeOutlined /> : <EyeInvisibleOutlined />}
                onClick={() => setShowDetections((v) => !v)}
              >
                显示检测框
              </Button>
            </div>
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

      {editingEffectiveArea && activeTract?.tract_pk === editingEffectiveArea ? (
        <Suspense fallback={<div style={LOADING}><Spin tip="加载 GIS 编辑器" /></div>}>
          <LazyEffectiveAreaEditor
            tractPk={editingEffectiveArea}
            tractLabel={activeTract.tract_id}
            imageryTiles={editorImageryTiles}
            onClose={() => {
              const next = new URLSearchParams(searchParams);
              next.delete("effective-area");
              setSearchParams(next, { replace: true });
            }}
          />
        </Suspense>
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

function outlineColorForTract(item: Pick<TiffAsset, "city" | "county" | "tract_id">): string {
  const key = [item.city || "", item.county || "", item.tract_id || ""].join("\u0000");
  return OUTLINE_COLORS[Math.abs(hashString(key)) % OUTLINE_COLORS.length];
}

function hashString(value: string): number {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 31 + value.charCodeAt(i)) | 0;
  }
  return hash;
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

function tiffTileUrl(tiff: TiffAsset): string {
  return `/api/v1/tiles/tiffs/${encodeURIComponent(tiff.phase_id)}/${encodeURIComponent(tiff.tiff_id)}/{z}/{x}/{y}`;
}

function filterObservationsByTiffs(data: FeatureCollection, tiffIds: string[]): FeatureCollection {
  const allowed = new Set(tiffIds.filter(Boolean));
  if (!allowed.size) return data;
  return {
    ...data,
    features: data.features.filter((feature) => allowed.has(String(feature.properties?.tiff_id ?? ""))),
  };
}

function summaryFromObservations(data: FeatureCollection, area?: number | null): TractSummary {
  const species: Record<string, number> = {};
  const allCrownAreas: number[] = [];
  const allCrownSizes: number[] = [];
  const allHeights: number[] = [];
  const bySpecies = new Map<string, {
    count: number;
    crownAreas: number[];
    crownSizes: number[];
    heights: number[];
  }>();
  for (const feature of data.features) {
    const label = String(feature.properties?.species || "未知");
    species[label] = (species[label] ?? 0) + 1;
    const crownArea = numericProp(feature, "crown_area_geo_real") ?? numericProp(feature, "crown_area_geo_est");
    const crownWidth = numericProp(feature, "crown_width_geo");
    const crownHeight = numericProp(feature, "crown_height_geo");
    const crownSize = crownWidth && crownHeight ? Math.sqrt(crownWidth * crownHeight) : crownArea ? Math.sqrt(crownArea) : undefined;
    const height = numericProp(feature, "height");
    if (crownArea !== undefined) allCrownAreas.push(crownArea);
    if (crownSize !== undefined) allCrownSizes.push(crownSize);
    if (height !== undefined && height <= 50) allHeights.push(height);
    const bucket = bySpecies.get(label) ?? { count: 0, crownAreas: [], crownSizes: [], heights: [] };
    bucket.count += 1;
    if (crownArea !== undefined) bucket.crownAreas.push(crownArea);
    if (crownSize !== undefined) bucket.crownSizes.push(crownSize);
    if (height !== undefined && height <= 50) bucket.heights.push(height);
    bySpecies.set(label, bucket);
  }
  const treeCount = data.features.length;
  const totalCrownArea = allCrownAreas.reduce((sum, value) => sum + value, 0);
  const speciesAnalysis = Object.fromEntries(
    [...bySpecies.entries()].map(([label, item]) => {
      const crownArea = item.crownAreas.reduce((sum, value) => sum + value, 0);
      return [
        label,
        {
          count: item.count,
          ratio: treeCount > 0 ? item.count / treeCount : 0,
          total_crown_area: crownArea,
          crown_area_geo: distributionFromValues(item.crownAreas),
          crown_size_geo: distributionFromValues(item.crownSizes),
          height: distributionFromValues(item.heights),
        },
      ];
    }),
  );
  return {
    tree_count: treeCount,
    species,
    crown_area_geo: distributionFromValues(allCrownAreas),
    crown_size_geo: distributionFromValues(allCrownSizes),
    height: distributionFromValues(allHeights),
    meta: {
      area_m2: area ?? null,
      canopy_cover_rate: area && area > 0 && totalCrownArea > 0 ? totalCrownArea / area : null,
      total_crown_area: totalCrownArea,
      species_analysis: speciesAnalysis,
    },
  };
}

function numericProp(feature: GeoFeature, key: string): number | undefined {
  const value = feature.properties?.[key];
  if (typeof value !== "number" || !Number.isFinite(value)) return undefined;
  return value;
}

function distributionFromValues(values: number[]): DistributionSummary {
  const xs = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  const n = xs.length;
  if (!n) return { n: 0 };
  const mean = xs.reduce((sum, value) => sum + value, 0) / n;
  const variance = xs.reduce((sum, value) => sum + (value - mean) ** 2, 0) / n;
  return {
    n,
    min: xs[0],
    max: xs[n - 1],
    mean,
    std: Math.sqrt(variance),
    p25: percentile(xs, 25),
    median: percentile(xs, 50),
    p75: percentile(xs, 75),
    p10: percentile(xs, 10),
    p90: percentile(xs, 90),
  };
}

function percentile(xs: number[], p: number): number {
  if (xs.length === 1) return xs[0];
  const idx = (p / 100) * (xs.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return xs[lo];
  return xs[lo] * (1 - (idx - lo)) + xs[hi] * (idx - lo);
}

function spreadNearbyMarkers(markers: MarkerSpec[], zoom: number): MarkerSpec[] {
  const groups: MarkerSpec[][] = [];
  for (const marker of markers) {
    const point = projectLngLat(marker.lngLat, zoom);
    const group = groups.find((items) => {
      const first = projectLngLat(items[0].lngLat, zoom);
      return Math.hypot(first[0] - point[0], first[1] - point[1]) < 25;
    });
    if (group) group.push(marker);
    else groups.push([marker]);
  }
  return groups.flatMap((group) => {
    if (group.length === 1) return group;
    const radius = Math.min(10, 5 + group.length * 1.5);
    return group.map((marker, idx) => {
      const angle = (Math.PI * 2 * idx) / group.length - Math.PI / 2;
      return {
        ...marker,
        offset: [Math.cos(angle) * radius, Math.sin(angle) * radius],
      };
    });
  });
}

function projectLngLat([lng, lat]: LngLat, zoom: number): [number, number] {
  const scale = 256 * 2 ** zoom;
  const sin = Math.sin((Math.max(-85.05112878, Math.min(85.05112878, lat)) * Math.PI) / 180);
  return [
    ((lng + 180) / 360) * scale,
    (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * scale,
  ];
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
  const features = fc.features.filter((feature) => {
    const raw = feature.properties?.species;
    const species = typeof raw === "string" && raw.trim() ? raw : "未知树种";
    return allowed.size === 0 || allowed.has(species);
  });
  if (!features.length) return [];
  const species = [...new Set(features.map(featureSpecies))];
  return [{
    id: DETECTION_PREFIX + "all",
    kind: "line" as const,
    color: speciesColorExpression(species, colors),
    opacity: 0.96,
    lineWidth: 2.2,
    data: { type: "FeatureCollection", features } as GeoJson,
  }];
}

function featureSpecies(feature: GeoFeature): string {
  const raw = feature.properties?.species;
  return typeof raw === "string" && raw.trim() ? raw : "未知树种";
}

function speciesColorExpression(species: string[], colors: Map<string, string>): unknown[] {
  const entries = species.flatMap((name, index) => [name, colors.get(name) ?? speciesColor(name, index)]);
  return ["match", ["coalesce", ["get", "species"], "未知树种"], ...entries, "#ffffff"];
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
  tiffs,
  activePhaseId,
  checkedKeys,
  width,
  onWidthChange,
  onCheckedKeysChange,
}: {
  tiffs: TiffAsset[];
  activePhaseId?: string;
  checkedKeys: string[];
  width: number;
  onWidthChange: (width: number) => void;
  onCheckedKeysChange: (keys: string[]) => void;
}) {
  function startResize(e: ReactMouseEvent<HTMLDivElement>) {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = width;
    const move = (event: MouseEvent) => {
      onWidthChange(clamp(startWidth + startX - event.clientX, 220, 420));
    };
    const up = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  }

  return (
    <div style={{ ...TIFF_TREE_PANEL, width }} className="custom-glass-scroll">
      <div style={RESIZE_HANDLE} onMouseDown={startResize} />
      <div style={PANEL_HEAD}>
        <span style={PANEL_TITLE}>影像文件</span>
        <span style={PANEL_SUBTITLE}>{activePhaseId || "未知时相"} · {tiffs.length} 图</span>
      </div>
      <Checkbox.Group
        value={checkedKeys}
        onChange={(keys) => onCheckedKeysChange(keys.map(String))}
        style={TIFF_LIST}
      >
        {tiffs.map((tiff) => (
          <label key={tiffKey(tiff)} style={TIFF_LIST_ROW}>
            <Checkbox value={tiffKey(tiff)} />
            <span style={TREE_LEAF_TITLE}>{tiff.file_name || tiff.tiff_id}</span>
            <Text type="secondary">{(tiff.observation_count ?? 0).toLocaleString()} 株</Text>
          </label>
        ))}
      </Checkbox.Group>
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
  tiffName,
  isSingleImageView,
  requestedTiff,
  width,
  onWidthChange,
}: {
  tract: Tract;
  group: TractGroup;
  imagery?: { available: boolean; source_format?: string | null; tile_service?: string | null };
  summary?: TractSummary;
  phaseTiffs?: TiffAsset[];
  speciesColors: Map<string, string>;
  onSelectPhase: (tract: Tract) => void;
  loading: boolean;
  tiffName?: string;
  isSingleImageView?: boolean;
  requestedTiff?: TiffAsset;
  width: number;
  onWidthChange: (width: number) => void;
}) {
  const activeAreaHm2 = isSingleImageView && requestedTiff
    ? (requestedTiff.effective_area_hm2 ?? requestedTiff.area_hm2 ?? (requestedTiff.geo_area ? (requestedTiff.geo_area > 1000 ? requestedTiff.geo_area / 10000 : requestedTiff.geo_area) : undefined))
    : (tract.effective_area_hm2 ?? tract.tract_phase_area_hm2 ?? tract.tract_area_hm2 ?? (tract.geo_area ? (tract.geo_area > 1000 ? tract.geo_area / 10000 : tract.geo_area) : undefined));

  const activeAreaM2 = activeAreaHm2 !== undefined ? Number(activeAreaHm2) * 10000 : (summary?.meta?.area_m2 ?? tract.geo_area);

  const metricSections = buildProfileMetricSections(summary, tract, speciesColors, activeAreaM2);
  const detectedTiffs = (phaseTiffs ?? []).filter((t) => t.has_detection || t.observation_count > 0);

  function startResize(e: ReactMouseEvent<HTMLDivElement>) {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = width;
    const move = (event: MouseEvent) => {
      onWidthChange(clamp(startWidth + event.clientX - startX, 320, 640));
    };
    const up = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  }

  const overallArea = activeAreaM2;
  const overallDensity = densityFromCount(summary?.tree_count ?? tract.observation_count ?? 0, overallArea) ?? summary?.density_per_ha;

  const displayAreaText = formatHm2(typeof activeAreaHm2 === "number" ? activeAreaHm2 : (activeAreaHm2 !== undefined && activeAreaHm2 !== null ? Number(activeAreaHm2) : null));

  return (
    <div style={{ ...PROFILE_PANEL, width }} className="custom-glass-scroll">
      <div style={PROFILE_RESIZE_HANDLE} onMouseDown={startResize} />
      <div style={PANEL_HEAD}>
        <div style={PROFILE_TITLE_GROUP}>
          <span style={PANEL_TITLE}>{tiffName ? `${tract.tract_id} - ${stripTiffSuffix(tiffName)}` : tract.tract_id}</span>
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
        <ProfileBigMetric label="面积(hm²)" value={displayAreaText} />
        <ProfileBigMetric label="种植密度(株/hm²)" value={formatDensity(overallDensity)} />
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
  crownSize?: DistributionSummary;
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
        <MiniMetric label="密度(株/hm²)" value={formatDensity(section.density)} />
        <MiniMetric label="冠幅和(m²)" value={formatDensity(section.crownArea)} />
      </div>
      <div style={PROFILE_DIST_STACK}>
        <ProfileDistRow label="冠尺寸(m)" value={<DistributionPills dist={section.crownSize} unit="" />} />
        <ProfileDistRow label="冠面积(m²)" value={<DistributionPills dist={section.crownAreaDist} unit="" />} />
        {hasDistribution(section.height) ? (
          <ProfileDistRow label="树高(m)" value={<DistributionPills dist={section.height} unit="" />} />
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

function ProfileDistRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div style={PROFILE_DIST_ROW}>
      <span>{label}</span>
      <div style={PROFILE_DIST_VALUE}>{value}</div>
    </div>
  );
}

function buildProfileMetricSections(
  summary: TractSummary | undefined,
  tract: Tract,
  speciesColors: Map<string, string>,
  activeAreaM2?: number,
): ProfileMetricSectionData[] {
  const effectiveAreaM2 = activeAreaM2 ?? summary?.meta?.area_m2 ?? tract.geo_area;
  const totalCount = summary?.tree_count ?? tract.observation_count ?? 0;
  const total: ProfileMetricSectionData = {
    key: "__total",
    label: "总体分析",
    color: "var(--glass-text)",
    total: true,
    count: totalCount,
    ratio: totalCount > 0 ? 1 : null,
    density: densityFromCount(totalCount, effectiveAreaM2) ?? summary?.density_per_ha ?? null,
    crownArea: summary?.meta?.total_crown_area ?? 0,
    crownSize: summary?.crown_size_geo ?? equivalentCrownSize(summary?.crown_width_geo, summary?.crown_height_geo),
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
        density: densityFromCount(count, effectiveAreaM2) ?? item.density_per_ha ?? null,
        crownArea: item.total_crown_area ?? (item.avg_crown_area ?? 0) * count,
        crownSize: item.crown_size_geo ?? equivalentCrownSize(item.crown_width_geo, item.crown_height_geo),
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
  return value.toLocaleString(undefined, { maximumFractionDigits: 1 });
}

function metersPerScreenPixel(camera: { center: LngLat; zoom: number }): number {
  const lat = Math.max(-85.05112878, Math.min(85.05112878, camera.center[1]));
  return (156543.03392804097 * Math.cos((lat * Math.PI) / 180)) / 2 ** camera.zoom;
}

function formatPixelSize(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "-";
  const displayVal = Math.max(0.001, value);
  if (displayVal >= 100) return displayVal.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (displayVal >= 1) return displayVal.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return displayVal.toLocaleString(undefined, { minimumFractionDigits: 3, maximumFractionDigits: 3 });
}

function densityFromCount(count: number, areaM2: number | undefined): number | null {
  if (typeof areaM2 !== "number" || areaM2 <= 0) return null;
  return count / (areaM2 / 10000);
}

function formatPercent(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return (value * 100).toLocaleString(undefined, { maximumFractionDigits: 1 }) + "%";
}

function hasDistribution(dist: DistributionSummary | undefined): dist is DistributionSummary {
  return Boolean(dist?.n && dist.n > 0);
}

function DistributionPills({ dist, unit }: { dist?: DistributionSummary; unit?: string }) {
  if (!hasDistribution(dist)) return <span>-</span>;
  const suffix = unit ? " " + unit : "";
  const values = [
    { label: "极小值", value: dist.min, isMedian: false },
    { label: "p25", value: dist.p25 ?? dist.p10, isMedian: false },
    { label: "中值", value: dist.median, isMedian: true },
    { label: "p75", value: dist.p75 ?? dist.p90, isMedian: false },
    { label: "极大值", value: dist.max, isMedian: false },
  ];
  return (
    <div style={DIST_PILL_WRAP}>
      <span style={DIST_BADGE_STATS}>统计</span>
      <Tooltip title="均值">
        <span style={DIST_NUMBER}>{formatMetric(dist.mean)}{suffix}</span>
      </Tooltip>
      <span style={DIST_PM}>±</span>
      <Tooltip title="标准差">
        <span style={DIST_NUMBER}>{formatMetric(dist.std)}</span>
      </Tooltip>
      <span style={DIST_BADGE_QUANTILE}>分位</span>
      {values.map((item, index) => (
        <span key={item.label} style={DIST_QUANTILE_ITEM}>
          {index > 0 ? <span style={DIST_SEPARATOR}>-</span> : null}
          <Tooltip title={item.label}>
            <span style={item.isMedian ? DIST_NUMBER_MEDIAN : DIST_NUMBER}>
              {formatMetric(item.value)}
            </span>
          </Tooltip>
        </span>
      ))}
    </div>
  );
}

function equivalentCrownSize(
  width: DistributionSummary | undefined,
  height: DistributionSummary | undefined,
): DistributionSummary | undefined {
  if (!hasDistribution(width) || !hasDistribution(height)) return undefined;
  const combine = (a?: number, b?: number) =>
    typeof a === "number" && typeof b === "number" && a >= 0 && b >= 0
      ? Math.sqrt(a * b)
      : undefined;
  return {
    n: Math.min(width.n ?? 0, height.n ?? 0),
    min: combine(width.min, height.min),
    max: combine(width.max, height.max),
    mean: combine(width.mean, height.mean),
    std: combine(width.std, height.std),
    p25: combine(width.p25 ?? width.p10, height.p25 ?? height.p10),
    median: combine(width.median, height.median),
    p75: combine(width.p75 ?? width.p90, height.p75 ?? height.p90),
  };
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
  width: "min(210px, 32vw)",
  height: 40,
  borderRadius: 20,
  display: "flex",
  alignItems: "center",
  paddingInline: 10,
};
const SEARCH_ICON: CSSProperties = { color: "var(--glass-text)", marginRight: 4, fontSize: 13 };
const SEARCH_SELECT: CSSProperties = { flex: 1 };
const TOP_LEFT_TOOLS: CSSProperties = {
  position: "absolute",
  top: 12,
  left: 12,
  zIndex: 8,
  display: "flex",
  alignItems: "center",
  gap: 6,
  maxWidth: "calc(100% - 24px)",
};
const SINGLE_PHASE_BUTTON: CSSProperties = {
  ...GLASS,
  height: 40,
  borderRadius: 20,
  paddingInline: 14,
  whiteSpace: "nowrap",
  border: "1px solid var(--glass-border)",
  color: "var(--glass-text)",
  fontSize: 12,
  fontWeight: 700,
  cursor: "pointer",
};
const SINGLE_PHASE_BUTTON_ACTIVE: CSSProperties = {
  ...SINGLE_PHASE_BUTTON,
  background: "rgba(16, 128, 99, 0.9)",
  borderColor: "rgba(185, 255, 228, 0.5)",
  color: "#ffffff",
};
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
  padding: "12px 16px 12px 12px",
  color: "var(--glass-text)",
};
const PROFILE_RESIZE_HANDLE: CSSProperties = {
  position: "absolute",
  right: 0,
  top: 0,
  bottom: 0,
  width: 8,
  cursor: "ew-resize",
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
  gridTemplateColumns: "55px minmax(0, 1fr)",
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
};
const DIST_PILL_WRAP: CSSProperties = {
  minWidth: 0,
  display: "flex",
  alignItems: "center",
  gap: 2,
  flexWrap: "wrap",
};
const DIST_BADGE_STATS: CSSProperties = {
  padding: "1px 5px",
  borderRadius: 6,
  color: "#0f3b30",
  background: "rgba(142, 225, 190, 0.72)",
  fontWeight: 800,
};
const DIST_BADGE_QUANTILE: CSSProperties = {
  ...DIST_BADGE_STATS,
  color: "#42310b",
  background: "rgba(242, 211, 130, 0.74)",
  marginLeft: 8,
};
const DIST_NUMBER: CSSProperties = {
  color: "var(--glass-text)",
  fontWeight: 760,
};
const DIST_NUMBER_MEDIAN: CSSProperties = {
  color: "#ffaa00",
  fontWeight: 850,
  background: "rgba(255, 170, 0, 0.16)",
  padding: "0 4px",
  borderRadius: 4,
  border: "1px solid rgba(255, 170, 0, 0.35)",
};
const DIST_PM: CSSProperties = {
  color: "var(--glass-muted)",
  fontWeight: 700,
};
const DIST_SEPARATOR: CSSProperties = {
  margin: "0 0px",
  color: "var(--glass-muted)",
};
const DIST_QUANTILE_ITEM: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
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
  bottom: 16,
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
const TREE_LEAF_TITLE: CSSProperties = { color: "var(--glass-text)" };
const TIFF_LIST: CSSProperties = {
  width: "100%",
  display: "grid",
  gap: 6,
};
const TIFF_LIST_ROW: CSSProperties = {
  width: "100%",
  minWidth: 0,
  display: "grid",
  gridTemplateColumns: "18px minmax(0, 1fr) auto",
  alignItems: "center",
  gap: 7,
  padding: "7px 8px",
  borderRadius: 10,
  background: "rgba(255, 255, 255, 0.12)",
  cursor: "pointer",
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
