import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { useParams } from "react-router-dom";
import { Button, Card, List, Segmented, Space, Spin, Tag } from "antd";
import { MapStage } from "../shared/ui/MapStage";
import { boundsOf, type MapController } from "../shared/map-core";
import { MeasureToolbar } from "../features/measure";
import { useTracts, type Tract } from "../entities/tract";
import { useObservations } from "../entities/observation";
import type { GeometryKind } from "../shared/api";
import { endpoints } from "../shared/api";

const OBS_LAYER = "observations";

// 地块工作台: 承接 v1.0 交互(地块列表 + 点/冠切换 + 报告/导出)到新 map-core 防腐层。
// 支持从总览图 /atlas/:tractId 丝滑飞入指定地块。
export function AtlasPage() {
  const { tractId } = useParams();
  const { data: tracts, isLoading: loadingTracts } = useTracts();
  const [selected, setSelected] = useState<Tract | null>(null);
  const [geometry, setGeometry] = useState<GeometryKind>("point");
  const { data: fc, isFetching: loadingObs } = useObservations(
    selected?.tract_id,
    geometry,
  );
  const mapRef = useRef<MapController | null>(null);
  const [mapCtl, setMapCtl] = useState<MapController | null>(null);

  // 路由携带 tractId 时优先选中该地块(总览图点击进入)。
  useEffect(() => {
    if (tractId && tracts) {
      const found = tracts.find((t) => t.tract_id === tractId);
      if (found) setSelected(found);
    }
  }, [tractId, tracts]);

  // 无指定时首条地块默认选中。
  useEffect(() => {
    if (!selected && !tractId && tracts && tracts.length > 0)
      setSelected(tracts[0]);
  }, [tracts, selected, tractId]);

  const draw = useCallback(() => {
    const map = mapRef.current;
    if (!map || !map.isReady()) return;
    const data = fc ?? { type: "FeatureCollection", features: [] };
    map.setGeoJsonLayer({
      id: OBS_LAYER,
      kind: geometry === "point" ? "point" : "polygon",
      data,
    });
    const b = boundsOf(data);
    if (b) map.fitBounds(b, 40);
  }, [fc, geometry]);

  useEffect(() => {
    draw();
  }, [draw]);

  const onReady = useCallback(
    (map: MapController) => {
      mapRef.current = map;
      setMapCtl(map);
      draw();
    },
    [draw],
  );

  const openReport = () =>
    selected &&
    window.open(endpoints.reportUrl(selected.tract_id, "pdf"), "_blank");
  const openExport = () =>
    selected &&
    window.open(endpoints.exportUrl(selected.tract_id, "geojson"), "_blank");

  const geometryOptions = [
    { label: "单木点", value: "point" },
    { label: "树冠面", value: "crown" },
  ];

  return (
    <div style={STAGE_WRAP}>
      <MapStage center={[110.3, 21.5]} zoom={9} onReady={onReady} />
      <MeasureToolbar map={mapCtl} />
      <Card style={PANEL} styles={CARD_STYLES} title="地块台账">
        <div style={TOOLBAR}>
          <Segmented
            size="small"
            value={geometry}
            onChange={(v) => setGeometry(v as GeometryKind)}
            options={geometryOptions}
          />
          {loadingObs ? <Spin size="small" /> : null}
        </div>
        <div style={LIST_WRAP}>
          {loadingTracts ? (
            <div style={CENTER}>
              <Spin />
            </div>
          ) : (
            <List
              size="small"
              dataSource={tracts ?? []}
              renderItem={(t) => (
                <List.Item
                  onClick={() => setSelected(t)}
                  style={itemStyle(selected?.tract_id === t.tract_id)}
                >
                  <List.Item.Meta
                    title={t.name || t.location || t.tract_id}
                    description={
                      <Space size={4} wrap>
                        <Tag>{t.acquisition_time || "-"}</Tag>
                        {t.active_run_id ? (
                          <Tag color="green">已发布</Tag>
                        ) : (
                          <Tag>未发布</Tag>
                        )}
                      </Space>
                    }
                  />
                </List.Item>
              )}
            />
          )}
        </div>
        <Space style={ACTIONS}>
          <Button size="small" disabled={!selected} onClick={openReport}>
            在线报告
          </Button>
          <Button size="small" disabled={!selected} onClick={openExport}>
            导出 GeoJSON
          </Button>
        </Space>
      </Card>
    </div>
  );
}

function itemStyle(active: boolean): CSSProperties {
  return {
    cursor: "pointer",
    background: active ? "#e6f4f1" : undefined,
    borderRadius: 6,
  };
}

const STAGE_WRAP: CSSProperties = {
  position: "relative",
  flex: 1,
  minHeight: 0,
};
const PANEL: CSSProperties = {
  position: "absolute",
  top: 16,
  left: 16,
  width: 320,
  maxHeight: "calc(100% - 32px)",
  boxShadow: "var(--shadow-2)",
};
const PANEL_BODY: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 8,
  maxHeight: "70vh",
};
const CARD_STYLES = { body: PANEL_BODY };
const TOOLBAR: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
};
const LIST_WRAP: CSSProperties = { overflow: "auto", flex: 1 };
const CENTER: CSSProperties = {
  display: "flex",
  justifyContent: "center",
  padding: 24,
};
const ACTIONS: CSSProperties = { justifyContent: "flex-end" };
