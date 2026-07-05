import { useMemo } from "react";
import type { CSSProperties, ReactNode } from "react";
import { Card, Col, Progress, Row, Space, Spin } from "antd";
import {
  AreaChartOutlined,
  BarChartOutlined,
  ClusterOutlined,
  PieChartOutlined,
} from "@ant-design/icons";
import { Link } from "react-router-dom";
import { PageContainer } from "../shared/ui/PageContainer";
import { useTractSummaries, useTracts, type Tract, type TractSummary } from "../entities/tract";
import { groupPhasesByLocation } from "../entities/phase";
import { tractCenter } from "../features/overview/tractGeo";

interface BarRow {
  label: string;
  value: number;
  display?: string;
}

interface AuditRow {
  id: string;
  name: string;
  time: string;
  trees: number;
  cover: number | null;
  crownArea: number;
  located: boolean;
  published: boolean;
}

export function DashboardPage() {
  const { data, isLoading } = useTracts();
  const tracts = data ?? [];
  const summariesQuery = useTractSummaries(tracts.length > 0);
  const summaries = summariesQuery.data ?? [];
  const groups = useMemo(() => groupPhasesByLocation(tracts), [tracts]);
  const summaryByTract = useMemo(() => indexSummaries(summaries), [summaries]);
  const stats = useMemo(() => buildStats(tracts, summaries), [tracts, summaries]);
  const auditRows = useMemo(
    () => buildAuditRows(tracts, summaryByTract),
    [tracts, summaryByTract],
  );
  const speciesRows = useMemo(() => buildSpeciesRows(summaries), [summaries]);
  const treeRows = useMemo(() => buildTreeRows(auditRows), [auditRows]);
  const areaRows = useMemo(() => buildAreaRows(auditRows), [auditRows]);
  const phaseRows = useMemo(() => bucketByTime(tracts), [tracts]);

  return (
    <PageContainer title="数据看板" subtitle="地块核查进度、树木统计、冠幅覆盖与数据质量。">
      {isLoading ? (
        <div style={CENTER}>
          <Spin />
        </div>
      ) : (
        <Space direction="vertical" size={16} style={FULL}>
          <Row gutter={[16, 16]}>
            <KpiCard
              title="已分析地块"
              value={groups.length.toLocaleString()}
              sub={`${tracts.length.toLocaleString()} 个入库时相`}
              icon={<ClusterOutlined />}
              accent="#118ab2"
            />
            <KpiCard
              title="总株数"
              value={stats.trees.toLocaleString()}
              sub={summariesQuery.isFetching ? "统计同步中" : "当前 active/latest run"}
              icon={<BarChartOutlined />}
              accent="#ef476f"
            />
            <KpiCard
              title="冠幅总面积"
              value={formatAreaValue(stats.crownArea)}
              sub={`监测面积 ${formatAreaValue(stats.area)}`}
              icon={<AreaChartOutlined />}
              accent="#2a9d8f"
            />
            <KpiCard
              title="总体覆盖率"
              value={formatPercent(stats.cover)}
              sub={`${stats.published}/${tracts.length} 个时相已发布`}
              icon={<PieChartOutlined />}
              accent="#7b2cbf"
            />
          </Row>

          <Row gutter={[16, 16]}>
            <Col xs={24} xl={16}>
              <PluginCard title="地块核查表" extra={`${auditRows.length} 条`}>
                <AuditTable rows={auditRows} />
              </PluginCard>
            </Col>
            <Col xs={24} xl={8}>
              <PluginCard title="树种组成" extra={`${speciesRows.length} 类`}>
                <BarList rows={speciesRows} empty="暂无树种统计" />
              </PluginCard>
            </Col>
          </Row>

          <Row gutter={[16, 16]}>
            <Col xs={24} lg={8}>
              <PluginCard title="株数排行">
                <BarList rows={treeRows} empty="暂无株数统计" />
              </PluginCard>
            </Col>
            <Col xs={24} lg={8}>
              <PluginCard title="冠幅面积排行">
                <BarList rows={areaRows} empty="暂无冠幅面积" />
              </PluginCard>
            </Col>
            <Col xs={24} lg={8}>
              <PluginCard title="时相与质量">
                <QualityRow label="空间定位" value={ratio(stats.located, tracts.length)} />
                <QualityRow label="发布状态" value={ratio(stats.published, tracts.length)} />
                <QualityRow label="面积字段" value={ratio(stats.withArea, tracts.length)} />
                <div style={QUALITY_SPLIT}>
                  <span style={MUTED_TEXT}>最近时相</span>
                  <strong style={DASH_TEXT}>{phaseRows[0]?.label ?? "-"}</strong>
                </div>
                <BarList rows={phaseRows} empty="暂无时相" compact />
              </PluginCard>
            </Col>
          </Row>
        </Space>
      )}
    </PageContainer>
  );
}

function indexSummaries(summaries: TractSummary[]): Map<string, TractSummary> {
  const out = new Map<string, TractSummary>();
  for (const summary of summaries) {
    if (summary.tract_id) out.set(summary.tract_id, summary);
  }
  return out;
}

function buildStats(tracts: Tract[], summaries: TractSummary[]) {
  const located = tracts.filter((t) => tractCenter(t)).length;
  const published = tracts.filter((t) => t.active_run_id).length;
  const withArea = tracts.filter((t) => typeof t.geo_area === "number").length;
  const area = tracts.reduce((sum, t) => sum + (t.geo_area ?? 0), 0);
  const summaryTrees = summaries.reduce((sum, s) => sum + (s.tree_count ?? 0), 0);
  const fallbackTrees = tracts.reduce((sum, t) => sum + (t.observation_count ?? 0), 0);
  const crownArea = summaries.reduce((sum, s) => sum + (s.meta?.total_crown_area ?? 0), 0);
  return {
    located,
    published,
    withArea,
    area,
    trees: summaryTrees || fallbackTrees,
    crownArea,
    cover: area > 0 && crownArea > 0 ? crownArea / area : null,
  };
}

function buildAuditRows(
  tracts: Tract[],
  summaryByTract: Map<string, TractSummary>,
): AuditRow[] {
  return tracts
    .map((tract) => {
      const summary = summaryByTract.get(tract.tract_id);
      return {
        id: tract.tract_id,
        name: tract.location || tract.name || tract.tract_id,
        time: tract.acquisition_time || "-",
        trees: summary?.tree_count ?? tract.observation_count ?? 0,
        cover: summary?.meta?.canopy_cover_rate ?? null,
        crownArea: summary?.meta?.total_crown_area ?? 0,
        located: Boolean(tractCenter(tract)),
        published: Boolean(tract.active_run_id),
      };
    })
    .sort((a, b) => b.trees - a.trees);
}

function buildSpeciesRows(summaries: TractSummary[]): BarRow[] {
  const counts = new Map<string, number>();
  for (const summary of summaries) {
    for (const [species, count] of Object.entries(summary.species ?? {})) {
      counts.set(species, (counts.get(species) ?? 0) + count);
    }
  }
  return [...counts.entries()]
    .map(([label, value]) => ({ label, value, display: value.toLocaleString() + " 株" }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 8);
}

function buildTreeRows(rows: AuditRow[]): BarRow[] {
  return rows.slice(0, 8).map((row) => ({
    label: row.name,
    value: row.trees,
    display: row.trees.toLocaleString() + " 株",
  }));
}

function buildAreaRows(rows: AuditRow[]): BarRow[] {
  return rows
    .filter((row) => row.crownArea > 0)
    .sort((a, b) => b.crownArea - a.crownArea)
    .slice(0, 8)
    .map((row) => ({
      label: row.name,
      value: row.crownArea,
      display: formatAreaValue(row.crownArea),
    }));
}

function bucketByTime(tracts: Tract[]): BarRow[] {
  const map = new Map<string, number>();
  for (const t of tracts) {
    const key = (t.acquisition_time || "未知").slice(0, 8);
    map.set(key, (map.get(key) ?? 0) + 1);
  }
  return [...map.entries()]
    .sort(([a], [b]) => b.localeCompare(a))
    .slice(0, 6)
    .map(([label, value]) => ({ label, value, display: value + " 期" }));
}

function ratio(value: number, total: number): number {
  if (total <= 0) return 0;
  return Math.round((value / total) * 100);
}

function KpiCard({
  title,
  value,
  sub,
  icon,
  accent,
}: {
  title: string;
  value: ReactNode;
  sub: string;
  icon: ReactNode;
  accent: string;
}) {
  return (
    <Col xs={12} xl={6}>
      <Card size="small" style={CARD} styles={{ body: KPI_BODY }}>
        <div style={KPI_HEAD}>
          <span style={{ ...KPI_ICON, color: accent, background: accent + "18" }}>{icon}</span>
          <span style={MUTED_TEXT}>{title}</span>
        </div>
        <div style={STAT_VALUE}>{value}</div>
        <span style={STAT_SUB}>{sub}</span>
      </Card>
    </Col>
  );
}

function PluginCard({
  title,
  extra,
  children,
}: {
  title: string;
  extra?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card
      size="small"
      title={<span style={SECTION_TITLE}>{title}</span>}
      extra={extra ? <span style={MUTED_TEXT}>{extra}</span> : null}
      style={CARD}
      styles={{ header: CARD_HEADER, body: PLUGIN_BODY }}
    >
      {children}
    </Card>
  );
}

function AuditTable({ rows }: { rows: AuditRow[] }) {
  if (rows.length === 0) return <span style={MUTED_TEXT}>暂无地块</span>;
  return (
    <div style={AUDIT_TABLE}>
      <div style={{ ...AUDIT_ROW, ...AUDIT_HEAD }}>
        <span>地块</span>
        <span>时相</span>
        <span>株数</span>
        <span>覆盖率</span>
        <span>冠幅和</span>
        <span>状态</span>
      </div>
      {rows.slice(0, 10).map((row) => (
        <div key={row.id} style={AUDIT_ROW}>
          <Link to={`/map/${encodeURIComponent(row.id)}`} style={AUDIT_NAME}>
            {row.name}
          </Link>
          <span>{row.time}</span>
          <strong>{row.trees.toLocaleString()}</strong>
          <span>{formatPercent(row.cover)}</span>
          <span>{formatAreaValue(row.crownArea)}</span>
          <span style={STATUS_STACK}>
            <i style={row.published ? STATUS_OK : STATUS_WARN} />
            {row.published ? "已发布" : "未发布"}
            <i style={row.located ? STATUS_OK : STATUS_WARN} />
            {row.located ? "已定位" : "缺坐标"}
          </span>
        </div>
      ))}
    </div>
  );
}

function QualityRow({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div style={QUALITY_LABEL}>
        <span style={DASH_TEXT}>{label}</span>
        <strong style={DASH_TEXT}>{value}%</strong>
      </div>
      <Progress percent={value} showInfo={false} strokeColor={progressColor(value)} />
    </div>
  );
}

function BarList({
  rows,
  empty,
  compact,
}: {
  rows: BarRow[];
  empty: string;
  compact?: boolean;
}) {
  const max = Math.max(...rows.map((r) => r.value), 1);
  if (rows.length === 0) return <span style={MUTED_TEXT}>{empty}</span>;
  return (
    <div style={{ ...BAR_LIST, gap: compact ? 8 : 12 }}>
      {rows.map((row, idx) => (
        <div key={row.label} style={BAR_ROW}>
          <div style={BAR_LABEL}>
            <span style={BAR_NAME}>{row.label}</span>
            <span style={MUTED_TEXT}>{row.display ?? row.value}</span>
          </div>
          <div style={BAR_TRACK}>
            <div
              style={{
                ...BAR_FILL,
                width: Math.max(8, (row.value / max) * 100) + "%",
                background: BAR_COLORS[idx % BAR_COLORS.length],
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function progressColor(value: number): string {
  if (value >= 80) return "#2a9d8f";
  if (value >= 50) return "#118ab2";
  return "#ef476f";
}

function formatAreaValue(m2: number): string {
  if (!Number.isFinite(m2) || m2 <= 0) return "-";
  if (m2 >= 1000000) return (m2 / 1000000).toFixed(2) + " km\u00b2";
  if (m2 >= 10000) return (m2 / 10000).toFixed(2) + " hm\u00b2";
  return m2.toLocaleString(undefined, { maximumFractionDigits: 1 }) + " m\u00b2";
}

function formatPercent(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return (value * 100).toLocaleString(undefined, { maximumFractionDigits: 1 }) + "%";
}

const BAR_COLORS = ["#ef476f", "#118ab2", "#2a9d8f", "#ffd166", "#7b2cbf"];
const FULL: CSSProperties = { width: "100%" };
const CENTER: CSSProperties = {
  display: "flex",
  justifyContent: "center",
  padding: 48,
};
const CARD: CSSProperties = {
  borderRadius: 8,
  background: "var(--color-surface)",
  borderColor: "var(--color-border)",
  boxShadow: "var(--shadow-1)",
  color: "var(--color-text)",
};
const KPI_BODY: CSSProperties = {
  minHeight: 116,
};
const CARD_HEADER: CSSProperties = {
  color: "var(--color-text)",
  borderBottomColor: "var(--color-border)",
};
const KPI_HEAD: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  marginBottom: 8,
};
const KPI_ICON: CSSProperties = {
  width: 30,
  height: 30,
  borderRadius: 8,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
};
const STAT_VALUE: CSSProperties = {
  color: "var(--color-text)",
  fontSize: 28,
  fontWeight: 760,
  lineHeight: 1.12,
  fontVariantNumeric: "tabular-nums",
};
const STAT_SUB: CSSProperties = {
  display: "block",
  marginTop: 4,
  fontSize: 12,
  color: "var(--color-text-muted)",
};
const SECTION_TITLE: CSSProperties = {
  color: "var(--color-text)",
  fontWeight: 750,
};
const MUTED_TEXT: CSSProperties = {
  color: "var(--color-text-muted)",
};
const DASH_TEXT: CSSProperties = {
  color: "var(--color-text)",
};
const PLUGIN_BODY: CSSProperties = {
  minHeight: 242,
  display: "flex",
  flexDirection: "column",
  gap: 12,
};
const AUDIT_TABLE: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 6,
};
const AUDIT_ROW: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(120px, 1.4fr) 88px 72px 72px 96px 150px",
  alignItems: "center",
  gap: 10,
  padding: "8px 10px",
  borderRadius: 8,
  background: "var(--color-bg)",
  color: "var(--color-text-muted)",
  fontSize: 12,
};
const AUDIT_HEAD: CSSProperties = {
  background: "transparent",
  color: "var(--color-text-muted)",
  fontWeight: 700,
};
const AUDIT_NAME: CSSProperties = {
  minWidth: 0,
  color: "var(--color-primary)",
  fontWeight: 700,
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
  textDecoration: "none",
};
const STATUS_STACK: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "8px auto 8px auto",
  alignItems: "center",
  gap: 5,
};
const STATUS_OK: CSSProperties = {
  display: "block",
  width: 7,
  height: 7,
  borderRadius: 999,
  background: "#2a9d8f",
};
const STATUS_WARN: CSSProperties = {
  ...STATUS_OK,
  background: "#ef476f",
};
const QUALITY_LABEL: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  marginBottom: 4,
};
const QUALITY_SPLIT: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  paddingTop: 2,
};
const BAR_LIST: CSSProperties = {
  display: "flex",
  flexDirection: "column",
};
const BAR_ROW: CSSProperties = { display: "flex", flexDirection: "column", gap: 5 };
const BAR_LABEL: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 10,
};
const BAR_NAME: CSSProperties = {
  maxWidth: 230,
  color: "var(--color-text)",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};
const BAR_TRACK: CSSProperties = {
  height: 8,
  background: "var(--color-bg)",
  borderRadius: 999,
  overflow: "hidden",
};
const BAR_FILL: CSSProperties = {
  height: "100%",
  borderRadius: 999,
};
