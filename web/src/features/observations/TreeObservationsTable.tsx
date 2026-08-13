import { useState, useMemo } from "react";
import {
    Button,
    Card,
    Empty,
    Input,
    Select,
    Slider,
    Space,
    Table,
    Tag,
    Typography,
} from "antd";
import type { TablePaginationConfig, TableProps } from "antd";
import {
    ClearOutlined,
    DownloadOutlined,
    EyeOutlined,
    ReloadOutlined,
    SearchOutlined,
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { endpoints, queryKeys, type TreeObservationItem } from "../../shared/api";
import { ExportColumnsModal } from "./ExportColumnsModal";
import { ObservationDetailDrawer } from "./ObservationDetailDrawer";

const { Text } = Typography;

interface TreeObservationsTableProps {
    initialTiffId?: string | null;
    initialRunId?: string | null;
    initialPhaseId?: string | null;
    initialTractId?: string | null;
}

function formatCenterCoords(v: unknown): { display: string; copyText: string } | null {
    if (!v) return null;

    let x: number | null = null;
    let y: number | null = null;

    if (typeof v === "string") {
        const pointMatch = v.match(/POINT\s*\(\s*([-\d.]+)\s+([-\d.]+)\s*\)/i);
        if (pointMatch) {
            x = parseFloat(pointMatch[1]);
            y = parseFloat(pointMatch[2]);
        } else {
            const pairMatch = v.match(/([-\d.]+)\s*[\s,]\s*([-\d.]+)/);
            if (pairMatch) {
                x = parseFloat(pairMatch[1]);
                y = parseFloat(pairMatch[2]);
            }
        }
    } else if (Array.isArray(v) && v.length >= 2) {
        x = typeof v[0] === "number" ? v[0] : parseFloat(String(v[0]));
        y = typeof v[1] === "number" ? v[1] : parseFloat(String(v[1]));
    } else if (typeof v === "object" && v !== null) {
        const obj = v as Record<string, unknown>;
        if (Array.isArray(obj.coordinates) && obj.coordinates.length >= 2) {
            x = Number(obj.coordinates[0]);
            y = Number(obj.coordinates[1]);
        } else if (obj.x != null && obj.y != null) {
            x = Number(obj.x);
            y = Number(obj.y);
        }
    }

    if (x != null && y != null && !isNaN(x) && !isNaN(y)) {
        const formattedX = x.toFixed(2);
        const formattedY = y.toFixed(2);
        const text = `(${formattedX}, ${formattedY})`;
        return { display: text, copyText: text };
    }

    const fallback = typeof v === "string" ? v : JSON.stringify(v);
    return { display: fallback, copyText: fallback };
}

export function TreeObservationsTable({
    initialTiffId,
    initialRunId,
    initialPhaseId,
    initialTractId,
}: TreeObservationsTableProps) {
    // 筛选与分页状态
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(50);
    const [sortBy, setSortBy] = useState<string>("observation_id");
    const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");

    const [keyword, setKeyword] = useState("");
    const [species, setSpecies] = useState<string | undefined>(undefined);
    const [minConfidence, setMinConfidence] = useState<number | undefined>(undefined);

    // 详情抽屉与导出弹窗状态
    const [selectedItem, setSelectedItem] = useState<TreeObservationItem | null>(null);
    const [detailOpen, setDetailOpen] = useState(false);
    const [exportOpen, setExportOpen] = useState(false);

    // 请求参数组装
    const queryParams = useMemo(() => {
        return {
            tiff_id: initialTiffId || undefined,
            run_id: initialRunId || undefined,
            phase_id: initialPhaseId || undefined,
            tract_id: initialTractId || undefined,
            species: species || undefined,
            min_confidence: minConfidence != null ? minConfidence / 100 : undefined,
            keyword: keyword.trim() || undefined,
            page,
            page_size: pageSize,
            sort_by: sortBy,
            sort_order: sortOrder,
        };
    }, [initialTiffId, initialRunId, initialPhaseId, initialTractId, species, minConfidence, keyword, page, pageSize, sortBy, sortOrder]);

    const { data, isLoading, isFetching, refetch } = useQuery({
        queryKey: queryKeys.treeObservations(queryParams),
        queryFn: () => endpoints.listTreeObservations(queryParams),
        placeholderData: (previousData) => previousData,
    });

    const handleTableChange: TableProps<TreeObservationItem>["onChange"] = (
        pagination: TablePaginationConfig,
        _filters,
        sorter
    ) => {
        if (pagination.current && pagination.current !== page) {
            setPage(pagination.current);
        }
        if (pagination.pageSize && pagination.pageSize !== pageSize) {
            setPageSize(pagination.pageSize);
            setPage(1);
        }

        if (!Array.isArray(sorter) && sorter.field) {
            setSortBy(String(sorter.field));
            setSortOrder(sorter.order === "descend" ? "desc" : "asc");
        }
    };

    const handleResetFilters = () => {
        setKeyword("");
        setSpecies(undefined);
        setMinConfidence(undefined);
        setPage(1);
    };

    const handleOpenDetail = (item: TreeObservationItem) => {
        setSelectedItem(item);
        setDetailOpen(true);
    };

    const columns: TableProps<TreeObservationItem>["columns"] = [
        {
            title: "序号",
            key: "rowIndex",
            width: 65,
            align: "center",
            render: (_: unknown, __: unknown, index: number) => (page - 1) * pageSize + index + 1,
        },
        {
            title: "观测ID",
            dataIndex: "observation_id",
            key: "observation_id",
            width: 170,
            ellipsis: true,
            sorter: true,
            render: (v: string) => <Text code copyable>{v}</Text>,
        },
        {
            title: "树种",
            dataIndex: "species",
            key: "species",
            width: 100,
            sorter: true,
            render: (v?: string | null) =>
                v ? <Tag color="green">{v}</Tag> : <Text type="secondary">未分类</Text>,
        },
        {
            title: "置信度",
            dataIndex: "confidence",
            key: "confidence",
            width: 90,
            sorter: true,
            render: (v?: number | null) => {
                if (v == null) return "-";
                const valStr = v.toFixed(2);
                const color = v >= 0.8 ? "green" : v >= 0.5 ? "blue" : "orange";
                return <Tag color={color}>{valStr}</Tag>;
            },
        },
        {
            title: "树高 (m)",
            dataIndex: "height",
            key: "height",
            width: 90,
            sorter: true,
            render: (v?: number | null) => (v != null ? v.toFixed(2) : "-"),
        },
        {
            title: "冠幅长×宽 (m)",
            key: "crown_size",
            width: 120,
            render: (_: unknown, row: TreeObservationItem) => {
                if (row.crown_width_geo == null && row.crown_height_geo == null) return "-";
                const w = row.crown_width_geo != null ? row.crown_width_geo.toFixed(2) : "-";
                const h = row.crown_height_geo != null ? row.crown_height_geo.toFixed(2) : "-";
                return `${w} × ${h}`;
            },
        },
        {
            title: "冠幅面积 (m²)",
            dataIndex: "crown_area_geo_est",
            key: "crown_area_geo_est",
            width: 110,
            sorter: true,
            render: (v?: number | null) => (v != null ? v.toFixed(2) : "-"),
        },
        {
            title: "估算体积 (m³)",
            dataIndex: "crown_volume_geo_est",
            key: "crown_volume_geo_est",
            width: 110,
            sorter: true,
            render: (v?: number | null) => (v != null ? v.toFixed(2) : "-"),
        },
        {
            title: "中心点坐标",
            dataIndex: "center_geom",
            key: "center_geom",
            width: 170,
            ellipsis: true,
            render: (v?: unknown) => {
                const formatted = formatCenterCoords(v);
                if (!formatted) return <Text type="secondary">-</Text>;
                return <Text code copyable={{ text: formatted.copyText }}>{formatted.display}</Text>;
            },
        },
        {
            title: "来源",
            dataIndex: "source",
            key: "source",
            width: 85,
            sorter: true,
            render: (v: string) => {
                const color = v === "manual" ? "orange" : v === "review" ? "cyan" : "default";
                return <Tag color={color}>{v}</Tag>;
            },
        },
        {
            title: "单木ID",
            dataIndex: "individual_id",
            key: "individual_id",
            width: 100,
            ellipsis: true,
            sorter: true,
            render: (v?: string | null) => (v ? <Text code copyable>{v}</Text> : <Text type="secondary">-</Text>),
        },
        {
            title: "操作",
            key: "action",
            width: 80,
            fixed: "right",
            align: "center",
            render: (_: unknown, row: TreeObservationItem) => (
                <Button
                    type="link"
                    size="small"
                    icon={<EyeOutlined />}
                    onClick={() => handleOpenDetail(row)}
                >
                    详情
                </Button>
            ),
        },
    ];

    return (
        <Card
            styles={{ body: { padding: "16px 20px" } }}
            style={{
                borderRadius: 8,
                boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
            }}
        >
            {/* 顶部工具与筛选栏 */}
            <div
                style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    flexWrap: "wrap",
                    gap: 12,
                    marginBottom: 16,
                }}
            >
                <Space wrap size="middle">
                    {/* 关键词搜索 */}
                    <Input
                        placeholder="搜索观测ID / 单木ID"
                        prefix={<SearchOutlined style={{ color: "var(--color-text-muted, #bfbfbf)" }} />}
                        allowClear
                        value={keyword}
                        onChange={(e) => {
                            setKeyword(e.target.value);
                            setPage(1);
                        }}
                        style={{ width: 220 }}
                    />

                    {/* 树种下拉筛选 */}
                    <Select
                        placeholder="全部树种"
                        allowClear
                        value={species}
                        onChange={(v) => {
                            setSpecies(v);
                            setPage(1);
                        }}
                        style={{ width: 150 }}
                        options={[
                            ...(data?.available_species || []).map((sp) => ({
                                label: sp,
                                value: sp,
                            })),
                        ]}
                    />

                    {/* 最低置信度过滤 */}
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <Text type="secondary" style={{ fontSize: 13, whiteSpace: "nowrap" }}>
                            最低置信度:
                        </Text>
                        <div style={{ width: 110 }}>
                            <Slider
                                min={0}
                                max={100}
                                step={5}
                                value={minConfidence ?? 0}
                                onChange={(val) => {
                                    setMinConfidence(val > 0 ? val : undefined);
                                    setPage(1);
                                }}
                                tooltip={{ formatter: (v) => `${v}%` }}
                            />
                        </div>
                        {minConfidence ? (
                            <Tag color="blue" closable onClose={() => setMinConfidence(undefined)}>
                                &ge; {minConfidence}%
                            </Tag>
                        ) : null}
                    </div>

                    {(keyword || species || minConfidence) && (
                        <Button icon={<ClearOutlined />} onClick={handleResetFilters} size="middle">
                            重置
                        </Button>
                    )}
                </Space>

                <Space size="small">
                    <Button
                        icon={<ReloadOutlined spin={isFetching} />}
                        onClick={() => refetch()}
                        loading={isLoading}
                    >
                        刷新
                    </Button>
                    <Button
                        type="primary"
                        icon={<DownloadOutlined />}
                        onClick={() => setExportOpen(true)}
                        disabled={!data?.items?.length}
                    >
                        导出 CSV
                    </Button>
                </Space>
            </div>

            {/* 数据表格 */}
            <Table<TreeObservationItem>
                rowKey="observation_id"
                columns={columns}
                dataSource={data?.items || []}
                loading={isLoading || isFetching}
                onChange={handleTableChange}
                scroll={{ x: 1400 }}
                size="middle"
                pagination={{
                    current: page,
                    pageSize: pageSize,
                    total: data?.total || 0,
                    pageSizeOptions: [20, 50, 100],
                    showSizeChanger: true,
                    showQuickJumper: true,
                    showTotal: (total) => (
                        <span style={{ color: "var(--color-text-secondary, #666)" }}>
                            共 <strong>{total.toLocaleString()}</strong> 株单木观测记录
                        </span>
                    ),
                }}
                locale={{
                    emptyText: <Empty description="未检索到符合条件的单木观测记录" />,
                }}
            />

            {/* 详情抽屉 */}
            <ObservationDetailDrawer
                open={detailOpen}
                onClose={() => setDetailOpen(false)}
                item={selectedItem}
            />

            {/* 自定义列导出弹窗 */}
            <ExportColumnsModal
                open={exportOpen}
                onClose={() => setExportOpen(false)}
                items={data?.items || []}
                total={data?.total || 0}
                filenamePrefix={`tree_obs_${initialRunId || initialTiffId || "export"}`}
            />
        </Card>
    );
}
