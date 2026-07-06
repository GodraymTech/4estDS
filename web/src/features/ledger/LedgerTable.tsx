import { useEffect, useMemo, useState } from "react";
import type { Key } from "react";
import type { CSSProperties } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button, Empty, Input, Modal, Space, Table, Tag, Tree, Typography, message } from "antd";
import type { DataNode } from "antd/es/tree";
import type { TableProps } from "antd";
import {
  ControlOutlined,
  DownloadOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { endpoints, queryKeys, type ArtifactNode, type JobHistoryItem } from "../../shared/api";

const { Text } = Typography;

// 监管台账: 面向 infer run 的成果陈设、预览与选择性导出。
export function LedgerTable() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const targetRun = searchParams.get("run_id") ?? undefined;
  const { data = [], isLoading } = useQuery({
    queryKey: queryKeys.jobs("infer"),
    queryFn: () => endpoints.listJobs("infer", 120),
    refetchInterval: 6000,
  });
  const [q, setQ] = useState("");
  const [expanded, setExpanded] = useState<readonly string[]>([]);
  const [exportRun, setExportRun] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (targetRun) setExpanded([targetRun]);
  }, [targetRun]);

  const rows = useMemo(() => {
    const kw = q.trim().toLowerCase();
    if (!kw) return data;
    return data.filter((r) =>
      [r.run_id, r.tract_id, r.input_path, r.model_arch]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(kw)),
    );
  }, [data, q]);

  const columns: TableProps<JobHistoryItem>["columns"] = [
    {
      title: "run_id",
      dataIndex: "run_id",
      key: "run_id",
      width: 94,
      render: (v: string) => <Text code>{v}</Text>,
    },
    {
      title: "地块",
      dataIndex: "tract_id",
      key: "tract_id",
      ellipsis: true,
      render: (v?: string | null) => v || "-",
    },
    {
      title: "面积",
      dataIndex: "geo_area",
      key: "geo_area",
      width: 120,
      align: "right",
      render: (v: number | null | undefined, r: JobHistoryItem) => formatArea(v, r.area_unit),
      sorter: (a, b) => (a.geo_area ?? 0) - (b.geo_area ?? 0),
    },
    {
      title: "检测株数",
      dataIndex: "observation_count",
      key: "observation_count",
      width: 110,
      align: "right",
      render: (v: number) => v.toLocaleString(),
      sorter: (a, b) => a.observation_count - b.observation_count,
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 92,
      render: (v: JobHistoryItem["status"]) => (
        <Tag color={v === "succeeded" ? "success" : v === "failed" ? "error" : "processing"}>
          {v === "succeeded" ? "已完成" : v === "failed" ? "失败" : "运行中"}
        </Tag>
      ),
    },
    {
      title: "开始时间",
      dataIndex: "started_at",
      key: "started_at",
      width: 184,
      render: (v?: string | null) => (v ? new Date(v).toLocaleString() : "-"),
    },
    {
      title: "操作",
      key: "actions",
      width: 280,
      render: (_: unknown, r) => (
        <Space size={4}>
          <Button
            size="small"
            type="link"
            icon={<ControlOutlined />}
            disabled={!r.tract_id}
            onClick={(e) => {
              e.stopPropagation();
              if (r.tract_id) navigate(`/map/${encodeURIComponent(r.tract_id)}`);
            }}
          >
            操作台
          </Button>
          <Button
            size="small"
            type="link"
            icon={<FileTextOutlined />}
            disabled={!r.tract_id}
            onClick={(e) => {
              e.stopPropagation();
              navigate(`/reports?run_id=${encodeURIComponent(r.run_id)}`);
            }}
          >
            报告
          </Button>
          <Button
            size="small"
            type="link"
            icon={<DownloadOutlined />}
            onClick={(e) => {
              e.stopPropagation();
              if (exportRun === r.run_id) {
                setExportRun(undefined);
              } else {
                setExpanded((old) => (old.includes(r.run_id) ? old : [...old, r.run_id]));
                setExportRun(r.run_id);
              }
            }}
          >
            选择导出
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <Space direction="vertical" size={12} style={FULL}>
      <Input.Search
        placeholder="搜索 run_id / 地块 / 输入路径 / 模型"
        allowClear
        onChange={(e) => setQ(e.target.value)}
        style={SEARCH}
      />
      <Table<JobHistoryItem>
        rowKey="run_id"
        size="small"
        loading={isLoading}
        columns={columns}
        dataSource={rows}
        pagination={PAGINATION}
        onRow={(r) => ({
          onClick: () => {
            setExpanded((old) => {
              const closing = old.includes(r.run_id);
              if (closing && exportRun === r.run_id) setExportRun(undefined);
              return closing ? old.filter((id) => id !== r.run_id) : [...old, r.run_id];
            });
          },
        })}
        expandable={{
          expandedRowKeys: expanded,
          onExpandedRowsChange: (keys) => setExpanded(keys.map(String)),
          expandedRowRender: (r) => (
            <RunArtifacts
              runId={r.run_id}
              exportMode={exportRun === r.run_id}
              onCloseExport={() => setExportRun(undefined)}
            />
          ),
        }}
      />
    </Space>
  );
}

function RunArtifacts({
  runId,
  exportMode,
  onCloseExport,
}: {
  runId: string;
  exportMode: boolean;
  onCloseExport: () => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["artifacts", runId],
    queryFn: () => endpoints.getArtifacts(runId),
  });
  const [checked, setChecked] = useState<Key[]>([]);
  const [expandedKeys, setExpandedKeys] = useState<Key[]>([]);
  const [preview, setPreview] = useState<ArtifactNode | null>(null);
  const [exportPath, setExportPath] = useState("");

  const treeData = useMemo(() => toTreeData(data?.tree ?? [], exportMode, setPreview), [data?.tree, exportMode]);
  const allKeys = useMemo(() => collectKeys(data?.tree ?? []), [data?.tree]);
  const topKeys = useMemo(() => (data?.tree ?? []).map((n) => n.path), [data?.tree]);

  useEffect(() => {
    if (exportMode) {
      setChecked(allKeys);
      setExpandedKeys(allKeys);
    } else {
      setExpandedKeys(topKeys);
    }
  }, [exportMode, allKeys.join("|"), topKeys.join("|")]);

  async function runExport() {
    try {
      const selected = checked.map(String);
      const res = await endpoints.exportArtifacts(runId, selected);
      window.location.href = endpoints.downloadArtifactUrl(res.url);
      message.success(exportPath.trim() ? "已打包，浏览器将下载；自定义位置请在保存对话框中选择。" : "已打包，浏览器将下载。");
      onCloseExport();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "导出失败");
    }
  }

  if (isLoading) return <div style={ARTIFACT_PANEL}>正在读取成果目录...</div>;
  if (!data?.available) return <Empty description="未找到运行成果目录" />;

  return (
    <div style={ARTIFACT_PANEL}>
      <div style={RUN_DIR_LINE}>
        <FolderOpenOutlined />
        <Text type="secondary" ellipsis>{data.run_dir}</Text>
      </div>
      <Tree
        showLine
        checkable={exportMode}
        checkedKeys={checked}
        expandedKeys={expandedKeys}
        onExpand={(keys) => setExpandedKeys(keys)}
        onCheck={(keys) => setChecked(Array.isArray(keys) ? keys : keys.checked)}
        treeData={treeData}
      />
      {exportMode ? (
        <div style={EXPORT_BAR}>
          <Input
            value={exportPath}
            onChange={(e) => setExportPath(e.target.value)}
            placeholder="默认全量导出至桌面'forestDS'文件夹"
          />
          <Button onClick={() => message.info("Web 版使用浏览器保存位置；桌面版文件夹选择后续接入。")}>
            选择位置
          </Button>
          <Button type="primary" icon={<DownloadOutlined />} onClick={runExport}>
            执行导出
          </Button>
        </div>
      ) : null}
      <PreviewModal runId={runId} node={preview} onClose={() => setPreview(null)} />
    </div>
  );
}

function toTreeData(
  nodes: ArtifactNode[],
  exportMode: boolean,
  setPreview: (node: ArtifactNode) => void,
): DataNode[] {
  return nodes.map((n) => ({
    key: n.path,
    title: (
      <span>
        {n.description ? <Text strong>{n.name}</Text> : n.name}
        {n.description ? <Text type="secondary"> - {n.description}</Text> : null}
        {!exportMode && n.type === "file" ? (
          <Button
            size="small"
            type="link"
            icon={<FileSearchOutlined />}
            disabled={!n.previewable}
            onClick={(e) => {
              e.stopPropagation();
              setPreview(n);
            }}
          >
            预览
          </Button>
        ) : null}
      </span>
    ),
    children: n.children ? toTreeData(n.children, exportMode, setPreview) : undefined,
  }));
}

function collectKeys(nodes: ArtifactNode[]): string[] {
  return nodes.flatMap((n) => [n.path, ...collectKeys(n.children ?? [])]);
}

function PreviewModal({ runId, node, onClose }: { runId: string; node: ArtifactNode | null; onClose: () => void }) {
  const url = node ? endpoints.previewArtifactUrl(runId, node.path) : "";
  const suffix = node?.name.split(".").pop()?.toLowerCase();
  const image = suffix && ["png", "jpg", "jpeg", "webp", "gif"].includes(suffix);
  const text = suffix && ["txt", "log", "md", "csv", "json", "geojson", "xml", "prj", "cpg"].includes(suffix);
  return (
    <Modal open={Boolean(node)} title={node?.name} onCancel={onClose} footer={null} width={920}>
      {!node ? null : image ? (
        <img src={url} alt={node.name} style={PREVIEW_IMAGE} />
      ) : text ? (
        <iframe src={url} title={node.name} style={PREVIEW_FRAME} />
      ) : suffix === "pdf" ? (
        <iframe src={url} title={node.name} style={PREVIEW_FRAME} />
      ) : (
        <Empty description="该文件类型不支持浏览器预览，请使用选择导出。" />
      )}
    </Modal>
  );
}

const FULL: CSSProperties = { width: "100%" };
const SEARCH: CSSProperties = { maxWidth: 360 };
const PAGINATION = { pageSize: 10, showSizeChanger: false } as const;
const ARTIFACT_PANEL: CSSProperties = {
  padding: 12,
  background: "color-mix(in srgb, var(--color-surface) 90%, var(--color-bg))",
};
const RUN_DIR_LINE: CSSProperties = {
  display: "flex",
  gap: 8,
  alignItems: "center",
  marginBottom: 8,
};
const EXPORT_BAR: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(0, 1fr) auto auto",
  gap: 8,
  marginTop: 12,
};
const PREVIEW_IMAGE: CSSProperties = { maxWidth: "100%", maxHeight: "70vh", display: "block", margin: "0 auto" };
const PREVIEW_FRAME: CSSProperties = { width: "100%", height: "70vh", border: "1px solid var(--color-border)" };

function formatArea(value?: number | null, unit?: string | null) {
  if (typeof value !== "number") return "-";
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 }) + (unit ? ` ${unit}` : "");
}
