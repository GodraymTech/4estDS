import { useSearchParams, useNavigate } from "react-router-dom";
import { Button, Space, Tag } from "antd";
import { ArrowLeftOutlined } from "@ant-design/icons";
import { PageContainer } from "../shared/ui/PageContainer";
import { TreeObservationsTable } from "../features/observations";

export function TreeObservationsPage() {
    const [searchParams] = useSearchParams();
    const navigate = useNavigate();

    const tiffId = searchParams.get("tiff_id");
    const runId = searchParams.get("run_id");
    const phaseId = searchParams.get("phase_id");
    const tractId = searchParams.get("tract_id");

    return (
        <PageContainer
            title="单木观测全量数据"
            subtitle="模型推理与人工核查产生的单木级细粒度观测记录。"
        >
            <div style={{ marginBottom: 16 }}>

                {/* 顶部操作与筛选上下文标识 */}
                <div
                    style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        flexWrap: "wrap",
                        gap: 12,
                        padding: "10px 16px",
                        background: "var(--color-surface)",
                        borderRadius: 8,
                        border: "1px solid var(--color-border)",
                    }}
                >
                    <Space wrap size="middle">
                        <Button
                            icon={<ArrowLeftOutlined />}
                            onClick={() => navigate("/ledger")}
                        >
                            返回
                        </Button>

                        <Space wrap size="small">
                            {runId ? (
                                <Tag color="purple">
                                    <strong>Run ID:</strong> {runId}
                                </Tag>
                            ) : (
                                <Tag color="default">全部 Run</Tag>
                            )}
                            {tiffId && (
                                <Tag color="blue">
                                    <strong>TIFF ID:</strong> {tiffId}
                                </Tag>
                            )}
                            {phaseId && (
                                <Tag color="cyan">
                                    <strong>时相:</strong> {phaseId}
                                </Tag>
                            )}
                            {tractId && (
                                <Tag color="green">
                                    <strong>地块:</strong> {tractId}
                                </Tag>
                            )}
                        </Space>
                    </Space>
                </div>
            </div>

            {/* 单木观测数据主表 */}
            <TreeObservationsTable
                initialTiffId={tiffId}
                initialRunId={runId}
                initialPhaseId={phaseId}
                initialTractId={tractId}
            />
        </PageContainer>
    );
}

export default TreeObservationsPage;
