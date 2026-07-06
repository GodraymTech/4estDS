import { useEffect, useMemo, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { Button, Empty, Input, Space, Spin, Tag, Tree, Typography } from "antd";
import type { DataNode } from "antd/es/tree";
import { DownloadOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { endpoints, queryKeys, type JobHistoryItem } from "../../shared/api";

const { Text } = Typography;

export function ReportHub() {
  const [searchParams] = useSearchParams();
  const requestedRun = searchParams.get("run_id") ?? undefined;
  const { data = [] } = useQuery({
    queryKey: queryKeys.jobs("infer"),
    queryFn: () => endpoints.listJobs("infer", 120),
    refetchInterval: 8000,
  });
  const [q, setQ] = useState("");
  const [runId, setRunId] = useState<string | undefined>(requestedRun);

  useEffect(() => {
    if (requestedRun) setRunId(requestedRun);
  }, [requestedRun]);

  const rows = useMemo(() => {
    const succeeded = data.filter((r) => r.status === "succeeded" && r.tract_id);
    const kw = q.trim().toLowerCase();
    if (!kw) return succeeded;
    return succeeded.filter((r) =>
      [r.run_id, r.tract_id, r.input_path]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(kw)),
    );
  }, [data, q]);

  const treeData = useMemo(() => buildReportTree(rows), [rows]);
  const selected = rows.find((r) => r.run_id === runId);
  const mdPath = selected?.tract_id ? `reports/report_${selected.tract_id}.md` : "";
  const pdfPath = selected?.tract_id ? `reports/report_${selected.tract_id}.pdf` : "";
  const pdfUrl = selected ? endpoints.downloadArtifactPathUrl(selected.run_id, pdfPath) : "";

  const report = useQuery({
    queryKey: ["report-md", selected?.run_id, mdPath],
    enabled: Boolean(selected && mdPath),
    queryFn: () => endpoints.getArtifactText(selected!.run_id, mdPath),
  });

  return (
    <div style={LAYOUT}>
      <aside style={SIDEBAR}>
        <Input.Search placeholder="搜索地理标识 / 时相 / run_id" allowClear onChange={(e) => setQ(e.target.value)} />
        <div style={TREE_WRAP}>
          {treeData.length ? (
            <Tree
              showLine
              defaultExpandAll
              selectedKeys={runId ? [runId] : []}
              treeData={treeData}
              onSelect={(keys) => {
                const key = String(keys[0] ?? "");
                if (key && rows.some((r) => r.run_id === key)) setRunId(key);
              }}
            />
          ) : (
            <Empty description="暂无成功报告" />
          )}
        </div>
      </aside>
      <main style={MAIN}>
        {selected?.tract_id ? (
          <>
            <div style={REPORT_TOOLBAR}>
              <Space size={8} wrap>
                <Text strong>{geoId(selected.tract_id)}</Text>
                <Tag>{phaseId(selected)}</Tag>
                <Text code>{selected.run_id}</Text>
              </Space>
              <Button icon={<DownloadOutlined />} href={pdfUrl}>
                PDF
              </Button>
            </div>
            <div style={REPORT_VIEW}>
              {report.isLoading ? (
                <div style={CENTER}><Spin /></div>
              ) : report.data ? (
                <MarkdownReport markdown={report.data} runId={selected.run_id} />
              ) : (
                <Empty description="未找到该 run 的 Markdown 报告" />
              )}
            </div>
          </>
        ) : (
          <Empty description="请选择左侧时相报告" />
        )}
      </main>
    </div>
  );
}

function MarkdownReport({ markdown, runId }: { markdown: string; runId: string }) {
  const lines = markdown.split(/\r?\n/);
  const nodes: ReactNode[] = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line || line === "---") continue;
    if (line.startsWith("![") && line.includes("](")) {
      const m = /^!\[([^\]]*)\]\(([^)]+)\)/.exec(line);
      if (m) {
        const name = m[2].replace(/^\.\/assets\//, "");
        nodes.push(
          <figure key={i} style={FIGURE}>
            <img loading="lazy" src={endpoints.previewArtifactUrl(runId, `reports/assets/${name}`)} alt={m[1]} style={REPORT_IMAGE} />
            <figcaption>{m[1]}</figcaption>
          </figure>,
        );
      }
      continue;
    }
    if (line.startsWith("# ")) nodes.push(<h1 key={i}>{line.slice(2)}</h1>);
    else if (line.startsWith("## ")) nodes.push(<h2 key={i}>{line.slice(3)}</h2>);
    else if (line.startsWith("### ")) nodes.push(<h3 key={i}>{line.slice(4)}</h3>);
    else if (line.startsWith(">")) nodes.push(<blockquote key={i}>{stripMd(line.replace(/^>\s*/, ""))}</blockquote>);
    else if (line.startsWith("- ")) nodes.push(<p key={i}>• {stripMd(line.slice(2))}</p>);
    else if (line.startsWith("|")) {
      const table: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) table.push(lines[i++].trim());
      i -= 1;
      nodes.push(renderTable(table, i));
    } else {
      nodes.push(<p key={i}>{stripMd(line)}</p>);
    }
  }
  return <article style={REPORT_ARTICLE}>{nodes}</article>;
}

function renderTable(lines: string[], key: number) {
  const rows = lines
    .filter((line) => !/^\|\s*:?-+:?\s*\|/.test(line))
    .map((line) => line.split("|").slice(1, -1).map((cell) => stripMd(cell.trim())));
  const [head, ...body] = rows;
  return (
    <div key={key} style={TABLE_WRAP}>
      <table style={REPORT_TABLE}>
        <thead><tr>{head?.map((c) => <th style={TH} key={c}>{c}</th>)}</tr></thead>
        <tbody>{body.map((row, idx) => <tr key={idx}>{row.map((c, j) => <td style={TD} key={j}>{c}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

function stripMd(text: string) {
  return text.replace(/\*\*/g, "").replace(/`/g, "");
}

function buildReportTree(rows: JobHistoryItem[]): DataNode[] {
  const groups = new Map<string, JobHistoryItem[]>();
  for (const row of rows) {
    const key = geoId(row.tract_id);
    groups.set(key, [...(groups.get(key) ?? []), row]);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b, "zh-Hans-CN"))
    .map(([geo, items]) => ({
      key: `geo:${geo}`,
      title: <Text strong>{geo}</Text>,
      children: items
        .sort((a, b) => phaseId(b).localeCompare(phaseId(a)))
        .map((item) => ({
          key: item.run_id,
          title: <Space size={6}><span>{phaseId(item)}</span><Text type="secondary" code>{item.run_id}</Text></Space>,
        })),
    }));
}

function geoId(tractId?: string | null) {
  if (!tractId) return "未命名地块";
  const match = /^tract_(.+)_([0-9]{8})_[^_]+$/.exec(tractId);
  return match?.[1] ?? tractId;
}

function phaseId(row: JobHistoryItem) {
  const match = row.tract_id ? /^tract_.+_([0-9]{8})_[^_]+$/.exec(row.tract_id) : null;
  if (match?.[1]) return match[1];
  return row.started_at ? new Date(row.started_at).toISOString().slice(0, 10).replace(/-/g, "") : row.run_id;
}

const LAYOUT: CSSProperties = { display: "grid", gridTemplateColumns: "320px minmax(0, 1fr)", gap: 16, minHeight: "calc(100vh - 220px)" };
const SIDEBAR: CSSProperties = { display: "flex", flexDirection: "column", gap: 12, minHeight: 0 };
const TREE_WRAP: CSSProperties = { overflow: "auto", minHeight: 0 };
const MAIN: CSSProperties = { display: "flex", minWidth: 0, minHeight: 0, flexDirection: "column", gap: 12 };
const REPORT_TOOLBAR: CSSProperties = { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 };
const REPORT_VIEW: CSSProperties = { overflow: "auto", minHeight: "72vh", border: "1px solid var(--color-border)", borderRadius: 6, background: "white" };
const REPORT_ARTICLE: CSSProperties = { maxWidth: 980, margin: "0 auto", padding: "28px 34px", lineHeight: 1.72, color: "#1f2f2b" };
const FIGURE: CSSProperties = { margin: "18px 0", textAlign: "center" };
const REPORT_IMAGE: CSSProperties = { maxWidth: "100%", maxHeight: 640, objectFit: "contain", borderRadius: 4 };
const TABLE_WRAP: CSSProperties = { overflowX: "auto", margin: "12px 0" };
const REPORT_TABLE: CSSProperties = { borderCollapse: "collapse", width: "100%", fontSize: 13 };
const TH: CSSProperties = { border: "1px solid #d7e1dd", padding: "7px 9px", background: "#eef5f2", textAlign: "left", whiteSpace: "nowrap" };
const TD: CSSProperties = { border: "1px solid #d7e1dd", padding: "7px 9px", whiteSpace: "nowrap" };
const CENTER: CSSProperties = { minHeight: 360, display: "flex", alignItems: "center", justifyContent: "center" };
