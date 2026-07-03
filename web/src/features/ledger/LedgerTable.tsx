import { useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Input, Space, Table, Tag } from "antd";
import type { TableProps } from "antd";
import { useTracts, type Tract } from "../../entities/tract";
import { endpoints } from "../../shared/api";

// 监管台账: 地块/时相/面积/发布状态的可检索记录 + 行操作(工作台/报告/导出)。
export function LedgerTable() {
  const { data: tracts, isLoading } = useTracts();
  const navigate = useNavigate();
  const [q, setQ] = useState("");

  const rows = useMemo(() => {
    const kw = q.trim().toLowerCase();
    const list = tracts ?? [];
    if (!kw) return list;
    return list.filter((t) =>
      [t.name, t.location, t.tract_id]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(kw)),
    );
  }, [tracts, q]);

  const columns: TableProps<Tract>["columns"] = [
    {
      title: "名称",
      key: "name",
      render: (_: unknown, t: Tract) => t.name || t.location || t.tract_id,
    },
    {
      title: "地点",
      dataIndex: "location",
      key: "location",
      render: (v?: string) => v || "-",
    },
    {
      title: "时相",
      dataIndex: "acquisition_time",
      key: "acq",
      render: (v?: string) => v || "-",
      sorter: (a: Tract, b: Tract) =>
        String(a.acquisition_time || "").localeCompare(
          String(b.acquisition_time || ""),
        ),
    },
    {
      title: "面积",
      dataIndex: "geo_area",
      key: "area",
      align: "right",
      render: (v: number | undefined, t: Tract) =>
        typeof v === "number"
          ? v.toLocaleString() + " " + (t.area_unit || "")
          : "-",
      sorter: (a: Tract, b: Tract) => (a.geo_area ?? 0) - (b.geo_area ?? 0),
    },
    {
      title: "状态",
      key: "status",
      filters: [
        { text: "已发布", value: "published" },
        { text: "未发布", value: "draft" },
      ],
      onFilter: (value, t) =>
        (value === "published") === Boolean(t.active_run_id),
      render: (_: unknown, t: Tract) =>
        t.active_run_id ? <Tag color="green">已发布</Tag> : <Tag>未发布</Tag>,
    },
    {
      title: "操作",
      key: "actions",
      render: (_: unknown, t: Tract) => (
        <Space size={4}>
          <Button
            size="small"
            type="link"
            onClick={() => navigate("/atlas/" + t.tract_id)}
          >
            工作台
          </Button>
          <Button
            size="small"
            type="link"
            onClick={() =>
              window.open(endpoints.reportUrl(t.tract_id, "pdf"), "_blank")
            }
          >
            报告
          </Button>
          <Button
            size="small"
            type="link"
            onClick={() =>
              window.open(endpoints.exportUrl(t.tract_id, "geojson"), "_blank")
            }
          >
            导出
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <Space direction="vertical" size={12} style={FULL}>
      <Input.Search
        placeholder="搜索名称 / 地点"
        allowClear
        onChange={(e) => setQ(e.target.value)}
        style={SEARCH}
      />
      <Table<Tract>
        rowKey="tract_id"
        size="small"
        loading={isLoading}
        columns={columns}
        dataSource={rows}
        pagination={PAGINATION}
      />
    </Space>
  );
}

const FULL: CSSProperties = { width: "100%" };
const SEARCH: CSSProperties = { maxWidth: 320 };
const PAGINATION = { pageSize: 10, showSizeChanger: false } as const;
