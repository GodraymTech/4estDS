import { useEffect, useMemo, useState } from "react"
import { Layout, List, Typography, Segmented, Button, Space, Tag, message, Empty, Spin } from "antd"
import {
  listTracts,
  getObservations,
  reportUrl,
  exportUrl,
  type Tract,
  type FeatureCollection,
} from "./api"
import MapView from "./MapView"

const { Sider, Content, Header } = Layout
const { Title, Text } = Typography

export default function App() {
  const [tracts, setTracts] = useState<Tract[]>([])
  const [loadingTracts, setLoadingTracts] = useState(true)
  const [selected, setSelected] = useState<Tract | null>(null)
  const [geometry, setGeometry] = useState<"point" | "crown">("point")
  const [fc, setFc] = useState<FeatureCollection | null>(null)
  const [loadingObs, setLoadingObs] = useState(false)

  useEffect(() => {
    listTracts()
      .then((rows) => {
        setTracts(rows)
        if (rows.length > 0) setSelected(rows[0])
      })
      .catch((e: Error) => message.error(e.message))
      .finally(() => setLoadingTracts(false))
  }, [])

  useEffect(() => {
    if (!selected) {
      setFc(null)
      return
    }
    setLoadingObs(true)
    getObservations(selected.tract_id, geometry)
      .then(setFc)
      .catch((e: Error) => message.error(e.message))
      .finally(() => setLoadingObs(false))
  }, [selected, geometry])

  const featureCount = useMemo(() => fc?.features.length ?? 0, [fc])

  return (
    <Layout style={FULL}>
      <Header style={HEADER}>
        <Title level={4} style={HEADER_TITLE}>
          4estDS · 红树林单木一张图
        </Title>
        <Text style={HEADER_SUB}>政府/企业级生态监测与台账</Text>
      </Header>
      <Layout>
        <Sider width={320} theme="light" style={SIDER}>
          <div style={SIDER_HEAD}>
            <Text strong>地块台账</Text>
            <Tag>{tracts.length}</Tag>
          </div>
          {loadingTracts ? (
            <div style={CENTER}>
              <Spin />
            </div>
          ) : tracts.length === 0 ? (
            <Empty description="暂无地块" style={PAD16} />
          ) : (
            <List
              dataSource={tracts}
              renderItem={(t) => (
                <List.Item onClick={() => setSelected(t)} style={itemStyle(selected, t)}>
                  <List.Item.Meta
                    title={t.name || t.location || t.tract_id}
                    description={
                      <Space size={4} wrap>
                        <Tag color="blue">{t.acquisition_time || "-"}</Tag>
                        {t.active_run_id ? <Tag color="green">已发布</Tag> : <Tag>未发布</Tag>}
                        {typeof t.geo_area === "number" ? (
                          <Text type="secondary">
                            {t.geo_area.toFixed(2)} {t.area_unit || ""}
                          </Text>
                        ) : null}
                      </Space>
                    }
                  />
                </List.Item>
              )}
            />
          )}
        </Sider>
        <Content style={CONTENT}>
          <div style={TOOLBAR}>
            <Space>
              <Segmented
                value={geometry}
                onChange={(v) => setGeometry(v as "point" | "crown")}
                options={[
                  { label: "单木点", value: "point" },
                  { label: "树冠面", value: "crown" },
                ]}
              />
              <Text type="secondary">要素: {featureCount}</Text>
              {loadingObs ? <Spin size="small" /> : null}
            </Space>
            <Space>
              <Button
                disabled={!selected}
                onClick={() => selected && window.open(reportUrl(selected.tract_id, "pdf"), "_blank")}
              >
                在线报告
              </Button>
              <Button
                disabled={!selected}
                onClick={() =>
                  selected && window.open(exportUrl(selected.tract_id, "geojson"), "_blank")
                }
              >
                导出 GeoJSON
              </Button>
            </Space>
          </div>
          <div style={MAP_WRAP}>
            <MapView data={fc} />
          </div>
        </Content>
      </Layout>
    </Layout>
  )
}

const FULL = { height: "100vh" } as const
const HEADER = { background: "#0f5132", display: "flex", alignItems: "baseline", gap: 16 } as const
const HEADER_TITLE = { color: "#fff", margin: 0 } as const
const HEADER_SUB = { color: "#c7e6d3" } as const
const SIDER = { borderRight: "1px solid #f0f0f0", overflowY: "auto" } as const
const SIDER_HEAD = {
  padding: "12px 16px",
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  borderBottom: "1px solid #f0f0f0",
} as const
const CONTENT = { position: "relative", display: "flex", flexDirection: "column" } as const
const TOOLBAR = {
  padding: "8px 16px",
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  borderBottom: "1px solid #f0f0f0",
  background: "#fff",
  zIndex: 1,
} as const
const MAP_WRAP = { position: "relative", flex: 1 } as const
const CENTER = { display: "flex", justifyContent: "center", padding: 24 } as const
const PAD16 = { padding: 16 } as const

function itemStyle(selected: Tract | null, t: Tract): CSSProperties {
  return {
    cursor: "pointer",
    paddingInline: 16,
    background: selected?.tract_id === t.tract_id ? "#e6f4ff" : undefined,
  }
}
