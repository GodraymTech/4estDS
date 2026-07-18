import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Divider,
  Empty,
  Input,
  Modal,
  Select,
  Space,
  Spin,
  Tag,
  Tooltip,
  message,
} from "antd";
import {
  BorderOutlined,
  DeleteOutlined,
  DragOutlined,
  MergeCellsOutlined,
  MinusCircleOutlined,
  PlusOutlined,
  RedoOutlined,
  SaveOutlined,
  ScissorOutlined,
  UndoOutlined,
} from "@ant-design/icons";
import maplibregl from "maplibre-gl";
import { useBlocker } from "react-router-dom";
import {
  buildInvalidAreaMask,
  cloneGeometry,
  effectiveAreaErrorMessage,
  formatHm2,
  geometryVertexCount,
  inspectEffectiveAreaImport,
  useEffectiveArea,
  useSaveEffectiveArea,
  type EffectiveAreaGeometry,
} from "../../entities/effective-area";
import { ApiError } from "../../shared/api";
import type { EffectiveAreaImportSource } from "../../shared/api";
import { GeometryEditorAdapter, type GeometryEditorTool } from "./GeometryEditorAdapter";
import { areaHm2, geometryBbox } from "./geometryOperations";
import "./EffectiveAreaEditor.css";

export interface EffectiveAreaEditorProps {
  tractPk: string;
  tractLabel: string;
  imageryTiles: string[];
  onClose: () => void;
}

const TOOLS: Array<{ key: GeometryEditorTool; label: string; icon: React.ReactNode }> = [
  { key: "select", label: "选择", icon: <DragOutlined /> },
  { key: "draw", label: "绘制", icon: <BorderOutlined /> },
  { key: "add", label: "增加", icon: <PlusOutlined /> },
  { key: "hole", label: "挖洞", icon: <MinusCircleOutlined /> },
  { key: "split", label: "分割", icon: <ScissorOutlined /> },
  { key: "merge", label: "合并", icon: <MergeCellsOutlined /> },
  { key: "delete", label: "删除", icon: <DeleteOutlined /> },
];

export function EffectiveAreaEditor(props: EffectiveAreaEditorProps) {
  const query = useEffectiveArea(props.tractPk);
  if (query.isLoading) return <div className="effective-editor-loading"><Spin tip="加载有效区域" /></div>;
  if (query.isError || !query.data) {
    return (
      <div className="effective-editor-loading">
        <Empty description={query.error instanceof Error ? query.error.message : "有效区域加载失败"} />
        <Button onClick={props.onClose}>返回地图</Button>
      </div>
    );
  }
  return <EditorWorkspace key={query.data.updated_at} {...props} data={query.data} />;
}

function EditorWorkspace({
  tractPk,
  tractLabel,
  imageryTiles,
  onClose,
  data,
}: EffectiveAreaEditorProps & { data: NonNullable<ReturnType<typeof useEffectiveArea>["data"]> }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const adapterRef = useRef<GeometryEditorAdapter | null>(null);
  const sourceRef = useRef<EffectiveAreaImportSource | null>(null);
  const initialRef = useRef(JSON.stringify(data.geometry));
  const [draft, setDraft] = useState(() => cloneGeometry(data.geometry));
  const [tool, setTool] = useState<GeometryEditorTool>("select");
  const [dirty, setDirty] = useState(false);
  const [invalidMaskVisible, setInvalidMaskVisible] = useState(true);
  const [cursor, setCursor] = useState<[number, number] | null>(null);
  const [zoom, setZoom] = useState(15);
  const [localPath, setLocalPath] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [importing, setImporting] = useState(false);
  const [importLayers, setImportLayers] = useState<string[]>([]);
  const [importLayer, setImportLayer] = useState<string>();
  const save = useSaveEffectiveArea(tractPk);
  const blocker = useBlocker(dirty);

  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [dirty]);

  useEffect(() => {
    if (blocker.state !== "blocked") return;
    Modal.confirm({
      title: "放弃未保存的有效区域？",
      content: "当前编辑尚未保存，离开后本次修改将丢失。",
      okText: "放弃并离开",
      okButtonProps: { danger: true },
      cancelText: "继续编辑",
      onOk: blocker.proceed,
      onCancel: blocker.reset,
    });
  }, [blocker]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const [west, south, east, north] = geometryBbox(data.boundary_geometry);
    const map = new maplibregl.Map({
      container,
      style: editorStyle(),
      center: [(west + east) / 2, (south + north) / 2],
      zoom: 15,
      attributionControl: false,
      maxZoom: 24,
    });
    mapRef.current = map;
    map.on("load", () => {
      imageryTiles.forEach((tile, index) => addImagery(map, tile, index));
      map.addSource("effective-boundary", { type: "geojson", data: featureOf(data.boundary_geometry) });
      map.addLayer({
        id: "effective-boundary-fill",
        type: "fill",
        source: "effective-boundary",
        paint: { "fill-color": "#52c99a", "fill-opacity": 0.05 },
      });
      map.addLayer({
        id: "effective-boundary-line",
        type: "line",
        source: "effective-boundary",
        paint: { "line-color": "#d9fff0", "line-width": 2, "line-dasharray": [3, 2] },
      });
      map.addSource("effective-invalid-mask", {
        type: "geojson",
        data: buildInvalidAreaMask(data.boundary_geometry, data.geometry) as never,
      });
      map.addLayer({
        id: "effective-invalid-mask",
        type: "fill",
        source: "effective-invalid-mask",
        paint: { "fill-color": "#28161a", "fill-opacity": 0.58 },
      });
      const adapter = new GeometryEditorAdapter(map, data.geometry);
      adapterRef.current = adapter;
      adapter.onChange((geometry) => {
        setDraft(geometry);
        setDirty(JSON.stringify(geometry) !== initialRef.current);
        updateMask(map, data.boundary_geometry, geometry);
      });
      map.fitBounds([[west, south], [east, north]], { padding: 72, maxZoom: 18, duration: 0 });
      setZoom(map.getZoom());
    });
    map.on("mousemove", (event) => setCursor([event.lngLat.lng, event.lngLat.lat]));
    map.on("zoom", () => setZoom(map.getZoom()));
    return () => {
      adapterRef.current?.destroy();
      adapterRef.current = null;
      map.remove();
      mapRef.current = null;
    };
  }, [data, imageryTiles]);

  useEffect(() => {
    const map = mapRef.current;
    if (map?.getLayer("effective-invalid-mask")) {
      map.setLayoutProperty("effective-invalid-mask", "visibility", invalidMaskVisible ? "visible" : "none");
    }
  }, [invalidMaskVisible]);

  const previewArea = useMemo(() => areaHm2(draft), [draft]);
  const validArea = previewArea > 0 && previewArea <= data.tract_area_hm2 * 1.0001;

  async function persist(clipToBoundary: boolean) {
    try {
      await save.mutateAsync({
        geometry: adapterRef.current?.getDraft() ?? draft,
        updated_at: data.updated_at,
        clip_to_boundary: clipToBoundary,
      });
      setDirty(false);
      message.success(clipToBoundary ? "已裁剪并保存有效区域" : "有效区域已保存");
      window.setTimeout(onClose, 0);
    } catch (error) {
      const failure = apiFailure(error);
      if (!clipToBoundary && failure.code === "outside_boundary") {
        Modal.confirm({
          title: "有效区域超出地块边界",
          content: "后端验证发现越界。是否明确确认，将草稿裁剪到完整地块边界后保存？",
          okText: "确认裁剪并保存",
          cancelText: "返回检查",
          onOk: () => persist(true),
        });
        return;
      }
      message.error(effectiveAreaErrorMessage(failure));
    }
  }

  async function inspectImport(source: EffectiveAreaImportSource) {
    setImporting(true);
    sourceRef.current = source;
    try {
      const result = await inspectEffectiveAreaImport(tractPk, source);
      setImportLayers(result.layers);
      setImportLayer(result.layer ?? undefined);
      adapterRef.current?.replaceDraft(result.geometry);
      if (result.requires_clip) message.warning("导入区域超出地块边界，保存时必须确认裁剪");
      else message.success(`已载入 ${result.polygon_count} 个面`);
    } catch (error) {
      message.error(effectiveAreaErrorMessage(apiFailure(error)));
    } finally {
      setImporting(false);
    }
  }

  return (
    <div className="effective-editor">
      <header className="effective-editor__topbar">
        <div>
          <strong>有效区域编辑器</strong>
          <span>{tractLabel}</span>
          <Tag color={dirty ? "gold" : "green"}>{dirty ? "未保存" : "已同步"}</Tag>
        </div>
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" icon={<SaveOutlined />} loading={save.isPending} disabled={!dirty || !validArea} onClick={() => persist(false)}>
            保存
          </Button>
        </Space>
      </header>

      <aside className="effective-editor__tools">
        {TOOLS.map((item) => (
          <Tooltip title={item.key === "delete" ? "选择后单击要删除的岛" : item.label} placement="right" key={item.key}>
            <Button
              type={tool === item.key ? "primary" : "text"}
              danger={item.key === "delete"}
              icon={item.icon}
              onClick={() => {
                setTool(item.key === "merge" ? "select" : item.key);
                adapterRef.current?.setTool(item.key);
              }}
            >
              {item.label}
            </Button>
          </Tooltip>
        ))}
        <Divider />
        <Button icon={<UndoOutlined />} onClick={() => adapterRef.current?.undo()}>撤销</Button>
        <Button icon={<RedoOutlined />} onClick={() => adapterRef.current?.redo()}>重做</Button>
      </aside>

      <main className="effective-editor__map" ref={containerRef} />

      <aside className="effective-editor__inspector">
        <section>
          <h3>面积</h3>
          <div className="effective-editor__metric"><span>地块面积</span><strong>{formatHm2(data.tract_area_hm2)} hm²</strong></div>
          <div className="effective-editor__metric"><span>草稿有效面积</span><strong>{formatHm2(previewArea)} hm²</strong></div>
          <div className="effective-editor__metric"><span>占比</span><strong>{((previewArea / data.tract_area_hm2) * 100).toFixed(1)}%</strong></div>
        </section>
        <section>
          <h3>验证</h3>
          <Alert
            type={validArea ? "success" : "warning"}
            showIcon
            message={validArea ? "前端预检通过" : "面积为空或超过地块面积"}
            description="自相交、CRS、精确越界与面积由后端 Shapely/Geod 最终校验。"
          />
          <Checkbox checked={invalidMaskVisible} onChange={(event) => setInvalidMaskVisible(event.target.checked)}>
            遮罩无效区
          </Checkbox>
        </section>
        <section>
          <h3>导入 GIS</h3>
          <input type="file" multiple accept=".json,.geojson,.zip,.shp,.dbf,.shx,.prj,.gpkg,.kml,.fgb" onChange={(event) => setFiles(Array.from(event.target.files ?? []))} />
          <div className="effective-editor__or">或</div>
          <Input value={localPath} onChange={(event) => setLocalPath(event.target.value)} placeholder="后端可访问的本地矢量路径" />
          {importLayers.length > 1 ? (
            <Select
              value={importLayer}
              options={importLayers.map((value) => ({ value, label: value }))}
              placeholder="选择图层"
              onChange={(layer) => {
                setImportLayer(layer);
                if (sourceRef.current) void inspectImport({ ...sourceRef.current, layer });
              }}
            />
          ) : null}
          <Button
            loading={importing}
            disabled={!files.length && !localPath.trim()}
            onClick={() => inspectImport(files.length ? { files, layer: importLayer } : { localPath: localPath.trim(), layer: importLayer })}
          >
            预检并载入
          </Button>
        </section>
      </aside>

      <footer className="effective-editor__statusbar">
        <span>坐标 {cursor ? `${cursor[0].toFixed(6)}, ${cursor[1].toFixed(6)}` : "—"}</span>
        <span>比例尺约 {formatScale(cursor?.[1] ?? 0, zoom)}</span>
        <span>缩放 {zoom.toFixed(1)}</span>
        <span>工具 {TOOLS.find((item) => item.key === tool)?.label ?? "选择"}</span>
        <span>顶点 {geometryVertexCount(draft)}</span>
      </footer>
    </div>
  );
}

function editorStyle(): maplibregl.StyleSpecification {
  return {
    version: 8,
    sources: {
      base: {
        type: "raster",
        tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
        tileSize: 256,
      },
    },
    layers: [{ id: "base", type: "raster", source: "base" }],
  };
}

function addImagery(map: maplibregl.Map, tile: string, index: number) {
  const id = `editor-tiff-${index}`;
  map.addSource(id, { type: "raster", tiles: [tile], tileSize: 256, minzoom: 12, maxzoom: 24 });
  map.addLayer({ id, type: "raster", source: id, paint: { "raster-opacity": 0.88 } });
}

function featureOf(geometry: EffectiveAreaGeometry): GeoJSON.Feature<GeoJSON.Polygon | GeoJSON.MultiPolygon> {
  return { type: "Feature", properties: {}, geometry: geometry as GeoJSON.Polygon | GeoJSON.MultiPolygon };
}

function updateMask(map: maplibregl.Map, boundary: EffectiveAreaGeometry, geometry: EffectiveAreaGeometry) {
  const source = map.getSource("effective-invalid-mask") as maplibregl.GeoJSONSource | undefined;
  source?.setData(buildInvalidAreaMask(boundary, geometry) as never);
}

function apiFailure(error: unknown) {
  if (error instanceof ApiError) {
    return { status: error.status, code: error.code, message: error.message };
  }
  return { message: error instanceof Error ? error.message : "有效区域操作失败" };
}

function formatScale(latitude: number, zoom: number): string {
  const meters = 100 * 156543.03392 * Math.cos((latitude * Math.PI) / 180) / 2 ** zoom;
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km/100px` : `${Math.max(1, Math.round(meters))} m/100px`;
}
