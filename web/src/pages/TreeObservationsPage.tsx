import { useSearchParams, useNavigate } from "react-router-dom";
import { Breadcrumb, Button, Space, Tag, Typography } from "antd";
import { ArrowLeftOutlined, TableOutlined } from "@ant-design/icons";
import { PageContainer } from "../shared/ui/PageContainer";
import { TreeObservationsTable } from "../features/observations";

const { Text } = Typography;

export function TreeObservationsPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const tiffId = searchParams.get("tiff_id");
  const runId = searchParams.get("run_id");
  const phaseId = searchParams.get("phase_id");
  const tractId = searchParams.get("tract_id");

  return (
    <PageContainer
      title="单木观测全量数据 (tree_observations)"
      subtitle="展示模型推理与人工核查产生的单木级细粒度观测记录，支持分页、多维过滤、自定义列导出与空间详情查看。"
    >
      <div style={{ marginBottom: 16 }}>
        {/* 面包屑导航 */}
        <Breadcrumb
          items={[
            {
              title: <a onClick={() => navigate("/ledger")}>监管台账</a>,
            },
            {
              title: (
                <Space size={4}>
                  <TableOutlined />
                  <span>单木观测表</span>
                </Space>
              ),
            },
          ]}
          style={{ marginBottom: 12 }}
        />

        {/* 顶部操作与筛选上下文标识 */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: 12,
            padding: "10px 16px",
            background: "var(--color-bg-card, #ffffff)",
            borderRadius: 8,
            border: "1px solid var(--color-border, #f0f0f0)",
          }}
        >
          <Space wrap size="middle">
            <Button
              icon={<ArrowLeftOutlined />}
              onClick={() => navigate("/ledger")}
            >
              返回台账
            </Button>

            <Space wrap size="small">
              <Text strong style={{ fontSize: 13 }}>当前数据上下文:</Text>
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
