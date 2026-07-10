import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Button,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Progress,
  Segmented,
  Space,
  Table,
  Tag,
  Tooltip,
  Tree,
  Typography,
  message,
} from "antd";
import type { DataNode } from "antd/es/tree";
import type { TableProps } from "antd";
import {
  ApartmentOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  FileAddOutlined,
  FileSearchOutlined,
  FolderOpenOutlined,
  InfoCircleOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { endpoints, queryKeys, type ArtifactNode, type AssetRow } from "../../shared/api";
import { formatAreaValue } from "../../shared/lib/format";

const { Text } = Typography;

type ViewMode = "list" | "tree";
type ModalMode = "create" | "edit" | null;

export function LedgerTable() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [form] = Form.useForm();
  const [q, setQ] = useState("");
  const [mode, setMode] = useState<ViewMode>("list");
  const [modalMode, setModalMode] = useState<ModalMode>(null);
  const [editing, setEditing] = useState<AssetRow | null>(null);
  const [expanded, setExpanded] = useState<readonly string[]>([]);
  const [cogProgress, setCogProgress] = useState(0);
  const [skipCogSuggestion, setSkipCogSuggestion] = useState(false);
  const lastInspectedPath = useRef("");

  const assets = useQuery({
    queryKey: queryKeys.assets,
    queryFn: endpoints.listAssets,
  });
  const inspect = useMutation({
    mutationFn: endpoints.inspectAssetImage,
    onSuccess: (data) => {
      setSkipCogSuggestion(false);
      form.setFieldsValue({
        city: data.city,
        county: data.county,
        town: data.town,
        tract_id: data.suggested_tract_id,
        phase_id: data.suggested_phase_id,
        image_name: data.image_name,
      });
      if (data.inspect_error) {
        message.warning("路径无法读取，已保留可推断默认值");
      } else if (data.geo_error) {
        message.warning(data.geo_error);
      } else {
        message.success("已读取影像默认属性");
      }
    },
    onError: (e) => message.error(e instanceof Error ? e.message : "影像检查失败"),
  });

  const convertCog = useMutation({
    mutationFn: endpoints.convertAssetCog,
    onSuccess: (data) => {
      setCogProgress(100);
      form.setFieldsValue({
        input_path: data.cog_display_path,
        image_name: stripTiffSuffix(data.cog_display_path),
      });
      lastInspectedPath.current = data.cog_display_path;
      inspect.mutate({ input_path: data.cog_display_path });
      message.success("COG 转换完成");
    },
    onError: (e) => message.error(e instanceof Error ? e.message : "COG 转换失败"),
  });

  const convertRowCog = useMutation({
    mutationFn: async (row: AssetRow) => {
      if (!row.source_path || !row.phase_id || !row.tiff_id) {
        throw new Error("该 TIFF 缺少可转换路径或资产标识");
      }
      const converted = await endpoints.convertAssetCog(row.source_path);
      const data = await endpoints.patchAssetTiff(row.phase_id, row.tiff_id, {
        new_path: converted.cog_path,
        image_name: stripTiffSuffix(converted.cog_display_path),
      });
      return { data, converted };
    },
    onSuccess: ({ data, converted }) => {
      queryClient.setQueryData(queryKeys.assets, data);
      queryClient.invalidateQueries({ queryKey: queryKeys.assets });
      queryClient.invalidateQueries({ queryKey: queryKeys.tiffs });
      message.success(`已转换为 COG：${converted.cog_display_path}`);
    },
    onError: (e) => message.error(e instanceof Error ? e.message : "COG 转换失败"),
  });

  const createTiff = useMutation({
    mutationFn: endpoints.createAssetTiff,
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.assets, data);
      queryClient.invalidateQueries({ queryKey: queryKeys.assets });
      queryClient.invalidateQueries({ queryKey: queryKeys.tiffs });
      setModalMode(null);
      form.resetFields();
      inspect.reset();
      setSkipCogSuggestion(false);
      lastInspectedPath.current = "";
      setCogProgress(0);
      message.success("TIFF 已写入资产库");
    },
    onError: (e) => message.error(e instanceof Error ? e.message : "录入失败"),
  });

  const patchTract = useMutation({
    mutationFn: ({ tractPk, values }: { tractPk: string; values: Record<string, unknown> }) =>
      endpoints.patchAssetTract(tractPk, values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.assets });
      queryClient.invalidateQueries({ queryKey: queryKeys.tiffs });
      setModalMode(null);
      setEditing(null);
      message.success("资产信息已更新");
    },
    onError: (e) => message.error(e instanceof Error ? e.message : "更新失败"),
  });

  const patchTiff = useMutation({
    mutationFn: ({ row, values }: { row: AssetRow; values: Record<string, unknown> }) =>
      endpoints.patchAssetTiff(row.phase_id as string, row.tiff_id as string, values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.assets });
      queryClient.invalidateQueries({ queryKey: queryKeys.tiffs });
      setModalMode(null);
      setEditing(null);
      message.success("影像信息已更新");
    },
    onError: (e) => message.error(e instanceof Error ? e.message : "更新失败"),
  });

  const deleteTiff = useMutation({
    mutationFn: ({ row, force }: { row: AssetRow; force: boolean }) =>
      endpoints.deleteAssetTiff(row.phase_id as string, row.tiff_id as string, force),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.assets, data);
      queryClient.invalidateQueries({ queryKey: queryKeys.assets });
      queryClient.invalidateQueries({ queryKey: queryKeys.tiffs });
      message.success("TIFF 已删除");
    },
    onError: (e, vars) => {
      const msg = e instanceof Error ? e.message : "删除失败";
      if (msg.includes("409") && !vars.force) {
        Modal.confirm({
          title: "确认删除已检测 TIFF",
          content: msg + "。该操作不可恢复。",
          okText: "确认删除",
          okButtonProps: { danger: true },
          cancelText: "取消",
          onOk: () => deleteTiff.mutate({ row: vars.row, force: true }),
        });
        return;
      }
      message.error(msg);
    },
  });

  const rows = useMemo(() => {
    const kw = q.trim().toLowerCase();
    const data = assets.data ?? [];
    if (!kw) return data;
    return data.filter((r) =>
      [r.city, r.county, r.town, r.tract_id, r.phase_id, r.image_name, r.run_id, r.status, r.source_path]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(kw)),
    );
  }, [assets.data, q]);

  const inputPath = Form.useWatch("input_path", form);

  useEffect(() => {
    if (!convertCog.isPending) return;
    setCogProgress(8);
    const timer = window.setInterval(() => {
      setCogProgress((value) => Math.min(92, value + Math.max(2, Math.round((92 - value) * 0.12))));
    }, 700);
    return () => window.clearInterval(timer);
  }, [convertCog.isPending]);

  useEffect(() => {
    if (modalMode !== "create") return;
    const value = String(inputPath || "").trim();
    if (!value || value.length < 3 || value === lastInspectedPath.current) return;
    const timer = window.setTimeout(() => {
      lastInspectedPath.current = value;
      inspect.mutate({ input_path: value });
    }, 600);
    return () => window.clearTimeout(timer);
  }, [inputPath, inspect, modalMode]);

  const columns: TableProps<AssetRow>["columns"] = [
    { title: "市", dataIndex: "city", key: "city", width: 92, render: empty },
    { title: "县", dataIndex: "county", key: "county", width: 106, render: empty },
    { title: "地块", dataIndex: "tract_id", key: "tract_id", width: 120, ellipsis: true, render: empty },
    { title: "时相", dataIndex: "phase_id", key: "phase_id", width: 96, render: empty },
    { title: "影像名", dataIndex: "image_name", key: "image_name", ellipsis: true, render: empty },
    { title: "运行ID", dataIndex: "run_id", key: "run_id", width: 86, render: (v?: string | null) => (v ? <Text code>{v}</Text> : "") },
    { title: "状态", dataIndex: "status", key: "status", width: 96, render: statusTag },
    {
      title: "TIFF状态",
      dataIndex: "tiff_type",
      key: "tiff_type",
      width: 168,
      render: (_: unknown, row) => tiffStatusCell(row),
    },
    {
      title: "面积",
      dataIndex: "geo_area",
      key: "geo_area",
      width: 112,
      align: "right",
      render: (v?: number | null) => formatAreaValue(v),
    },
    {
      title: "株数",
      dataIndex: "observation_count",
      key: "observation_count",
      width: 86,
      align: "right",
      render: (v?: number) => (v ? v.toLocaleString() : ""),
    },
    { title: "检测时间", dataIndex: "detected_at", key: "detected_at", width: 170, render: formatTime },
    {
      title: "操作",
      key: "actions",
      width: 230,
      render: (_: unknown, row) => (
        <Space size={2}>
          <Tooltip title="地块视野">
            <Button type="link" size="small" icon={<EyeOutlined />} disabled={!row.tract_id} onClick={() => openMap(row)}>
              操作台
            </Button>
          </Tooltip>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>
            编辑
          </Button>
          {row.tiff_id && row.phase_id ? (
            <Popconfirm
              title="删除 TIFF"
              description={row.status === "已检测" ? "该 TIFF 已检测，下一步会要求危险确认。" : "确认删除该未检测 TIFF？"}
              okText="删除"
              cancelText="取消"
              onConfirm={() => deleteTiff.mutate({ row, force: false })}
            >
              <Button danger type="link" size="small" icon={<DeleteOutlined />}>
                删除
              </Button>
            </Popconfirm>
          ) : null}
        </Space>
      ),
    },
  ];

  function openMap(row: AssetRow) {
    if (!row.city || !row.county || !row.tract_id || !row.phase_id) return;
    const base = [
      "/map",
      encodeURIComponent(row.city),
      encodeURIComponent(row.county),
      encodeURIComponent(row.tract_id),
      encodeURIComponent(row.phase_id),
    ].join("/");
    if (row.phase_id && row.image_name) {
      navigate(`${base}/${encodeURIComponent(row.image_name)}`);
      return;
    }
    navigate(base);
  }

  function openCreate() {
    setEditing(null);
    setModalMode("create");
    inspect.reset();
    convertCog.reset();
    setCogProgress(0);
    setSkipCogSuggestion(false);
    lastInspectedPath.current = "";
    form.resetFields();
  }

  function openEdit(row: AssetRow) {
    setEditing(row);
    setModalMode("edit");
    form.setFieldsValue({
      city: row.city,
      county: row.county,
      town: row.town,
      tract_id: row.tract_id,
      phase_id: row.phase_id,
      image_name: row.image_name,
      new_path: row.source_path,
    });
  }

  async function submitModal() {
    const values = await form.validateFields();
    if (modalMode === "create") {
      createTiff.mutate(values);
      return;
    }
    if (!editing) return;
    if (editing.tract_pk) {
      patchTract.mutate({ tractPk: editing.tract_pk, values });
    }
    if (editing.tiff_id && editing.phase_id) {
      patchTiff.mutate({ row: editing, values });
    }
  }

  function tiffStatusCell(row: AssetRow) {
    const type = row.tiff_type || "invalid";
    if (type === "COG" || type === "ext_ovr") {
      return <Tag color="success">{tiffTypeLabel(type)} · 可瓦片</Tag>;
    }
    if (type === "normal" || type === "tiled") {
      const converting =
        convertRowCog.isPending
        && convertRowCog.variables?.phase_id === row.phase_id
        && convertRowCog.variables?.tiff_id === row.tiff_id;
      return (
        <Space size={4}>
          <Tag color="warning">{tiffTypeLabel(type)}</Tag>
          <Button size="small" type="link" loading={converting} disabled={!row.source_path} onClick={() => convertRowCog.mutate(row)}>
            转 COG
          </Button>
        </Space>
      );
    }
    return <Tag color="error">{tiffTypeLabel(type)}</Tag>;
  }

  return (
    <Space direction="vertical" size={12} style={FULL}>
      <div style={TOOL_ROW}>
        <Input.Search
          placeholder="搜索市 / 县 / 乡镇 / 地块 / 时相 / 影像 / 运行"
          allowClear
          onChange={(e) => setQ(e.target.value)}
          style={SEARCH}
        />
        <Space wrap size={8}>
          <Segmented
            value={mode}
            onChange={(v) => setMode(v as ViewMode)}
            options={[
              { label: "列表展示", value: "list", icon: <DatabaseOutlined /> },
              { label: "树状展示", value: "tree", icon: <ApartmentOutlined /> },
            ]}
          />
          <Button icon={<FileAddOutlined />} type="primary" onClick={openCreate}>
            录入 TIFF
          </Button>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => {
              queryClient.invalidateQueries({ queryKey: queryKeys.assets });
              queryClient.invalidateQueries({ queryKey: queryKeys.tiffs });
            }}
          >
            刷新
          </Button>
        </Space>
      </div>

      {mode === "list" ? (
        <Table<AssetRow>
          rowKey={rowKey}
          size="small"
          loading={assets.isLoading}
          columns={columns}
          dataSource={rows}
          pagination={PAGINATION}
          expandable={{
            expandedRowKeys: expanded,
            onExpandedRowsChange: (keys) => setExpanded(keys.map(String)),
            rowExpandable: (row) => Boolean(row.run_id),
            expandedRowRender: (row) => (row.run_id ? <RunArtifacts runId={row.run_id} /> : null),
          }}
        />
      ) : (
        <div style={TREE_PANEL}>
          {rows.length ? <Tree showLine defaultExpandAll treeData={buildAssetTree(rows, openMap, openEdit)} /> : <Empty description="暂无资产" />}
        </div>
      )}

      <Modal
        open={Boolean(modalMode)}
        title={modalMode === "create" ? "录入 TIFF" : "编辑资产"}
        onCancel={() => {
          setModalMode(null);
          inspect.reset();
          convertCog.reset();
          setCogProgress(0);
          setSkipCogSuggestion(false);
          lastInspectedPath.current = "";
        }}
        onOk={submitModal}
        confirmLoading={createTiff.isPending || patchTract.isPending || patchTiff.isPending}
        okButtonProps={{ disabled: convertCog.isPending }}
        width={760}
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          {modalMode === "create" ? (
            <>
              <Form.Item name="input_path" label="TIFF 路径" rules={[{ required: true, message: "请输入 TIFF 路径" }]}>
                <Input.Search
                  placeholder="输入本机 TIFF 路径"
                  enterButton="读取属性"
                  loading={inspect.isPending}
                  onSearch={(value) => {
                    const trimmed = value.trim();
                    if (!trimmed) return;
                    lastInspectedPath.current = trimmed;
                    inspect.mutate({ input_path: trimmed });
                  }}
                />
              </Form.Item>
              {inspect.data ? (
                <div style={INSPECT_PANEL}>
                  <div><Text type="secondary">读取状态：</Text>{inspect.data.inspect_error ? <Text type="danger">{inspect.data.inspect_error}</Text> : <Text type="success">可读取</Text>}</div>
                  <div><Text type="secondary">TIFF 类型：</Text><Text strong>{inspect.data.tiff_type_label || "-"}</Text></div>
                  {inspect.data.cog_required && !skipCogSuggestion ? (
                    <Space direction="vertical" size={6} style={FULL}>
                      <Space size={8} wrap>
                        <Button
                          size="small"
                          type="primary"
                          loading={convertCog.isPending}
                          onClick={() => {
                            const path = form.getFieldValue("input_path");
                            if (path) convertCog.mutate(String(path));
                          }}
                        >
                          转为 COG
                        </Button>
                        <Button size="small" disabled={convertCog.isPending} onClick={() => setSkipCogSuggestion(true)}>
                          暂不转换
                        </Button>
                        <Tooltip title="为缓解内存占用，强烈建议转为 COG（Cloud Optimized GeoTIFF）。">
                          <InfoCircleOutlined style={INFO_ICON} />
                        </Tooltip>
                      </Space>
                      {convertCog.isPending || cogProgress > 0 ? <Progress percent={cogProgress} size="small" /> : null}
                    </Space>
                  ) : null}
                  {convertCog.data ? (
                    <div style={COG_RESULT}>
                      <div><Text type="secondary">新路径：</Text><Text code>{convertCog.data.cog_display_path}</Text></div>
                      <Text type="secondary">转换确认无误后，可自行删除原始 tif/tiff、tif.ovr 等旁路文件。</Text>
                    </div>
                  ) : null}
                </div>
              ) : null}
              <Alert type="info" showIcon message="确认后会写入地块、时相和 TIFF 表；未检测影像也会出现在资产库。" style={ALERT} />
            </>
          ) : null}
          <div style={FORM_GRID}>
            <Form.Item name="city" label="市">
              <Input placeholder="默认识别市" />
            </Form.Item>
            <Form.Item name="county" label="县 / 区">
              <Input placeholder="默认识别县/区" />
            </Form.Item>
            <Form.Item name="town" label="乡镇">
              <Input placeholder="默认识别乡镇" />
            </Form.Item>
            <Form.Item name="tract_id" label="地块名">
              <Input placeholder="默认使用影像文件名" />
            </Form.Item>
            <Form.Item name="phase_id" label="时相">
              <Input placeholder="YYYYMMDD" />
            </Form.Item>
            <Form.Item name="image_name" label="影像名">
              <Input placeholder="默认使用文件名，不含后缀" />
            </Form.Item>
            {modalMode === "edit" ? (
              <Form.Item name="new_path" label="新路径">
                <Input placeholder="追加到路径版本" />
              </Form.Item>
            ) : null}
          </div>
        </Form>
      </Modal>
    </Space>
  );
}

function RunArtifacts({ runId }: { runId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["artifacts", runId],
    queryFn: () => endpoints.getArtifacts(runId),
  });
  const [preview, setPreview] = useState<ArtifactNode | null>(null);
  const treeData = useMemo(() => toTreeData(data?.tree ?? [], setPreview), [data?.tree]);
  if (isLoading) return <div style={ARTIFACT_PANEL}>正在读取成果目录...</div>;
  if (!data?.available) return <Empty description="未找到运行成果目录" />;
  return (
    <div style={ARTIFACT_PANEL}>
      <div style={RUN_DIR_LINE}>
        <FolderOpenOutlined />
        <Text type="secondary" ellipsis>{data.run_dir}</Text>
      </div>
      <Tree showLine treeData={treeData} />
      <PreviewModal runId={runId} node={preview} onClose={() => setPreview(null)} />
    </div>
  );
}

function toTreeData(nodes: ArtifactNode[], setPreview: (node: ArtifactNode) => void): DataNode[] {
  return nodes.map((n) => ({
    key: n.path,
    title: (
      <span>
        {n.description ? <Text strong>{n.name}</Text> : n.name}
        {n.description ? <Text type="secondary"> - {n.description}</Text> : null}
        {n.type === "file" ? (
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
    children: n.children ? toTreeData(n.children, setPreview) : undefined,
  }));
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
      ) : text || suffix === "pdf" ? (
        <iframe src={url} title={node.name} style={PREVIEW_FRAME} />
      ) : (
        <Empty description="该文件类型不支持浏览器预览" />
      )}
    </Modal>
  );
}

function buildAssetTree(rows: AssetRow[], openMap: (row: AssetRow) => void, openEdit: (row: AssetRow) => void): DataNode[] {
  const root = new Map<string, Map<string, Map<string, Map<string, AssetRow[]>>>>();
  for (const row of rows) {
    const city = row.city || "未知";
    const county = row.county || "未知";
    const tract = row.tract_id || "未知";
    const phase = row.phase_id || "未知";
    const counties = root.get(city) ?? new Map();
    const tracts = counties.get(county) ?? new Map();
    const phases = tracts.get(tract) ?? new Map();
    const leaves = phases.get(phase) ?? [];
    leaves.push(row);
    phases.set(phase, leaves);
    tracts.set(tract, phases);
    counties.set(county, tracts);
    root.set(city, counties);
  }
  return [...root.entries()].map(([city, counties]) => ({
    key: "city:" + city,
    title: city,
    children: [...counties.entries()].map(([county, tracts]) => ({
      key: "county:" + city + ":" + county,
      title: county,
      children: [...tracts.entries()].map(([tract, phases]) => ({
        key: "tract:" + city + ":" + county + ":" + tract,
        title: tract,
        children: [...phases.entries()].map(([phase, leaves]) => ({
          key: "phase:" + city + ":" + county + ":" + tract + ":" + phase,
          title: phase,
          children: leaves.map((row) => ({
            key: rowKey(row),
            title: <TreeLeaf row={row} openMap={openMap} openEdit={openEdit} />,
          })),
        })),
      })),
    })),
  }));
}

function TreeLeaf({ row, openMap, openEdit }: { row: AssetRow; openMap: (row: AssetRow) => void; openEdit: (row: AssetRow) => void }) {
  return (
    <Space size={8} wrap>
      <Text>{row.image_name || row.tiff_id || "未知影像"}</Text>
      {statusTag(row.status)}
      {row.run_id ? <Text code>{row.run_id}</Text> : null}
      <Text type="secondary">{row.observation_count ? row.observation_count.toLocaleString() + " 株" : ""}</Text>
      <Button size="small" type="link" icon={<EyeOutlined />} onClick={(e) => { e.stopPropagation(); openMap(row); }}>
        地块视野
      </Button>
      <Button size="small" type="link" icon={<EditOutlined />} onClick={(e) => { e.stopPropagation(); openEdit(row); }}>
        编辑
      </Button>
    </Space>
  );
}

function empty(value?: string | null) {
  return value || "";
}

function rowKey(row: AssetRow): string {
  return [row.city, row.county, row.tract_id, row.phase_id, row.tiff_id, row.run_id].filter(Boolean).join(":");
}

function stripTiffSuffix(path: string): string {
  const name = path.split(/[\\/]/).pop() || path;
  return name.replace(/\.(tif|tiff)$/i, "");
}

function statusTag(value: string) {
  const color = value === "已检测" ? "success" : value === "检测失败" ? "error" : value === "检测中" ? "processing" : "default";
  return <Tag color={color}>{value || "未检测"}</Tag>;
}

function formatTime(value?: string | null) {
  return value ? new Date(value).toLocaleString() : "";
}

function tiffTypeLabel(value?: string | null) {
  if (value === "COG") return "COG";
  if (value === "ext_ovr") return "带ovr";
  if (value === "tiled") return "Tiled";
  if (value === "normal") return "普通";
  return "不可用";
}

const FULL: CSSProperties = { width: "100%" };
const TOOL_ROW: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  gap: 12,
  flexWrap: "wrap",
};
const SEARCH: CSSProperties = { width: "min(480px, 100%)" };
const PAGINATION = { pageSize: 12, showSizeChanger: false } as const;
const TREE_PANEL: CSSProperties = {
  border: "1px solid var(--color-border)",
  borderRadius: 8,
  padding: 12,
  background: "var(--color-surface)",
};
const ALERT: CSSProperties = { marginBottom: 12 };
const INSPECT_PANEL: CSSProperties = {
  display: "grid",
  gap: 6,
  marginTop: -6,
  marginBottom: 12,
  padding: 10,
  border: "1px solid var(--color-border)",
  borderRadius: 6,
  background: "color-mix(in srgb, var(--color-surface) 86%, var(--color-bg))",
  fontSize: 12,
};
const INFO_ICON: CSSProperties = { color: "var(--color-primary)" };
const COG_RESULT: CSSProperties = {
  display: "grid",
  gap: 4,
  paddingTop: 4,
};
const FORM_GRID: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
  gap: "0 12px",
};
const ARTIFACT_PANEL: CSSProperties = {
  padding: 12,
  background: "color-mix(in srgb, var(--color-surface) 90%, var(--color-bg))",
};
const RUN_DIR_LINE: CSSProperties = { display: "flex", gap: 8, alignItems: "center", marginBottom: 8 };
const PREVIEW_IMAGE: CSSProperties = { maxWidth: "100%", maxHeight: "70vh", display: "block", margin: "0 auto" };
const PREVIEW_FRAME: CSSProperties = { width: "100%", height: "70vh", border: "1px solid var(--color-border)" };
