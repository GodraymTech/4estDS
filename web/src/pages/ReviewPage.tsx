import { useMemo, useState } from "react";
import { App, Button, Card, Empty, Popconfirm, Segmented, Select, Space, Spin, Table, Tag, Tooltip, Typography } from "antd";
import { DeleteOutlined, PlayCircleOutlined, PlusOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { useCreateReview, useDeleteReview, useReviews } from "../entities/review";
import type { ReviewMode, ReviewSession } from "../entities/review";
import { ReviewWorkbench } from "../features/review-workbench";
import { endpoints, queryKeys } from "../shared/api";
import "./ReviewPage.css";

const { Title, Paragraph, Text } = Typography;

export default function ReviewPage() {
  const { sessionId } = useParams();
  if (sessionId) return <ReviewWorkbench sessionId={sessionId} />;
  return <ReviewHome />;
}

function ReviewHome() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const sessions = useReviews();
  const assets = useQuery({ queryKey: queryKeys.assets, queryFn: endpoints.listAssets });
  const create = useCreateReview();
  const deleteReview = useDeleteReview();
  const [mode, setMode] = useState<ReviewMode>("inherit");
  const [assetKey, setAssetKey] = useState<string>();

  const candidates = useMemo(() => (assets.data ?? []).filter((item) => item.phase_id && item.tiff_id), [assets.data]);
  const selected = candidates.find((item) => `${item.phase_id}/${item.tiff_id}` === assetKey);

  async function start() {
    if (!selected?.phase_id || !selected.tiff_id) return;
    try {
      const session = await create.mutateAsync({ phase_id: selected.phase_id, tiff_id: selected.tiff_id, mode });
      navigate(`/review/${session.session_id}`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "创建复核会话失败");
    }
  }

  async function handleDelete(sessionIdStr: string) {
    try {
      await deleteReview.mutateAsync(sessionIdStr);
      message.success("复核草稿已删除");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "删除草稿失败");
    }
  }

  function formatDate(isoStr?: string) {
    if (!isoStr) return "—";
    try {
      return new Date(isoStr).toLocaleString("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      });
    } catch {
      return isoStr;
    }
  }

  return (
    <div style={{ padding: 24, overflow: "auto" }}>
      <Title level={2}>智能复核</Title>
      <Paragraph type="secondary">
        依托先进的AI辅助标注功能，实现已推理资产的深度核查。
      </Paragraph>

      <Card title="新建复核会话" style={{ marginBottom: 20 }}>
        <Space direction="vertical" size={16} style={{ width: "100%" }}>
          <Space wrap size={16} align="center">
            <Select
              showSearch
              style={{ width: 420 }}
              size="large"
              value={assetKey}
              placeholder="请选择要复核的 TIFF 影像"
              optionFilterProp="label"
              options={candidates.map((item) => ({
                value: `${item.phase_id}/${item.tiff_id}`,
                label: `${item.city ?? "—"} ${item.tract_id ?? "—"} · ${item.phase_id} / ${item.image_name ?? item.tiff_id}`,
              }))}
              onChange={setAssetKey}
            />

            <div className="apple-capsule-wrapper">
              <span className="apple-capsule-label">模式:</span>
              <Segmented
                className="apple-capsule-segmented"
                value={mode}
                options={[
                  {
                    value: "inherit",
                    label: (
                      <Tooltip title="对已有的推理结果进行增删查改">
                        <span className="apple-pill-item">
                          <span>继承</span>
                        </span>
                      </Tooltip>
                    ),
                  },
                  {
                    value: "fresh",
                    label: (
                      <Tooltip title="不加载已有推理结果，从空白画布开始">
                        <span className="apple-pill-item">
                          <span>新启</span>
                        </span>
                      </Tooltip>
                    ),
                  },
                ]}
                onChange={(val) => setMode(val as ReviewMode)}
              />
            </div>

            <Button
              type="primary"
              size="large"
              icon={<PlusOutlined />}
              disabled={!selected || (mode === "inherit" && !selected.active_run_id)}
              loading={create.isPending}
              onClick={start}
            >
              创建会话
            </Button>
          </Space>

          {selected && mode === "inherit" && !selected.active_run_id && (
            <Text type="warning" style={{ fontSize: 11 }}>
              ⚠️ 该 TIFF 尚无正式检测结果，请切换模式为“新启”。
            </Text>
          )}
        </Space>
      </Card>

      <Card title="最近草稿">
        {sessions.isLoading ? (
          <Spin />
        ) : sessions.data?.length ? (
          <Table<ReviewSession>
            rowKey="session_id"
            pagination={{ pageSize: 10 }}
            dataSource={sessions.data}
            columns={[
              {
                title: "影像资产",
                render: (_, row) => (
                  <div>
                    <Text strong>{row.image_name ?? row.tiff_id}</Text>
                    <div>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {row.city ?? "—"} · {row.tract_id ?? "—"} ({row.phase_id})
                      </Text>
                    </div>
                  </div>
                ),
              },
              {
                title: "模式",
                render: (_, row) => (
                  <Tag color={row.mode === "inherit" ? "blue" : "purple"}>
                    {row.mode === "inherit" ? "继承" : "新启"}
                  </Tag>
                ),
              },
              {
                title: "状态",
                render: (_, row) => (
                  <Tag color={row.status === "active" ? "processing" : row.status === "published" ? "success" : "default"}>
                    {row.status === "active" ? "复核中" : row.status === "published" ? "已发布" : "已取消"}
                  </Tag>
                ),
              },
              {
                title: "更新时间",
                render: (_, row) => formatDate(row.updated_at),
              },
              {
                title: "操作",
                render: (_, row) => (
                  <Space size={8}>
                    {row.status === "active" && (
                      <Button
                        type="link"
                        icon={<PlayCircleOutlined />}
                        onClick={() => navigate(`/review/${row.session_id}`)}
                      >
                        继续复核
                      </Button>
                    )}
                    {row.published_run_id && <Text code>{row.published_run_id}</Text>}
                    <Popconfirm
                      title="删除草稿"
                      description="确定要永久删除此复核草稿吗？此操作无法撤销。"
                      onConfirm={() => handleDelete(row.session_id)}
                      okText="确定删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                    >
                      <Button type="text" danger icon={<DeleteOutlined />} aria-label="删除草稿" />
                    </Popconfirm>
                  </Space>
                ),
              },
            ]}
          />
        ) : (
          <Empty description="暂无复核草稿" />
        )}
      </Card>
    </div>
  );
}
