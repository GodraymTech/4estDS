import { useMemo, useState } from "react";
import { Button, Card, Empty, Segmented, Select, Space, Spin, Table, Tag, Typography, message } from "antd";
import { PlayCircleOutlined, PlusOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { useCreateReview, useReviews } from "../entities/review";
import type { ReviewMode, ReviewSession } from "../entities/review";
import { ReviewWorkbench } from "../features/review-workbench";
import { endpoints, queryKeys } from "../shared/api";

const { Title, Paragraph, Text } = Typography;

export default function ReviewPage() {
  const { sessionId } = useParams();
  if (sessionId) return <ReviewWorkbench sessionId={sessionId} />;
  return <ReviewHome />;
}

function ReviewHome() {
  const navigate = useNavigate();
  const sessions = useReviews();
  const assets = useQuery({ queryKey: queryKeys.assets, queryFn: endpoints.listAssets });
  const create = useCreateReview();
  const [mode, setMode] = useState<ReviewMode>("based_on_active");
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

  return (
    <div style={{ padding: 24, overflow: "auto" }}>
      <Title level={2}>智能复核</Title>
      <Paragraph type="secondary">每个会话只处理一个 TIFF。草稿持续写入服务端，只有发布才创建 review run 并切换正式结果。</Paragraph>
      <Card title="开始单图复核" style={{ marginBottom: 20 }}>
        <Space wrap>
          <Select
            showSearch
            style={{ minWidth: 360 }}
            value={assetKey}
            placeholder="选择时相 / TIFF"
            optionFilterProp="label"
            options={candidates.map((item) => ({
              value: `${item.phase_id}/${item.tiff_id}`,
              label: `${item.city ?? "—"} ${item.tract_id ?? "—"} · ${item.phase_id} / ${item.image_name ?? item.tiff_id}`,
            }))}
            onChange={setAssetKey}
          />
          <Segmented
            value={mode}
            options={[
              { value: "based_on_active", label: "基于正式结果" },
              { value: "from_scratch", label: "从 0 开始" },
            ]}
            onChange={(value) => setMode(value as ReviewMode)}
          />
          <Button type="primary" icon={<PlusOutlined />} disabled={!selected || (mode === "based_on_active" && !selected.active_run_id)} loading={create.isPending} onClick={start}>
            创建会话
          </Button>
        </Space>
        {selected && mode === "based_on_active" && !selected.active_run_id ? <Text type="warning">该 TIFF 尚无正式结果，请选择“从 0 开始”。</Text> : null}
      </Card>

      <Card title="最近草稿">
        {sessions.isLoading ? <Spin /> : sessions.data?.length ? (
          <Table<ReviewSession>
            rowKey="session_id"
            pagination={{ pageSize: 10 }}
            dataSource={sessions.data}
            columns={[
              { title: "时相 / TIFF", render: (_, row) => `${row.phase_id} / ${row.tiff_id}` },
              { title: "模式", render: (_, row) => row.mode === "based_on_active" ? "基于正式结果" : "从 0 开始" },
              { title: "版本", dataIndex: "revision", width: 90 },
              { title: "状态", render: (_, row) => <Tag color={row.status === "active" ? "processing" : row.status === "published" ? "success" : "default"}>{row.status}</Tag> },
              { title: "更新时间", dataIndex: "updated_at" },
              {
                title: "操作",
                render: (_, row) => row.status === "active"
                  ? <Button type="link" icon={<PlayCircleOutlined />} onClick={() => navigate(`/review/${row.session_id}`)}>继续复核</Button>
                  : row.published_run_id ? <Text code>{row.published_run_id}</Text> : null,
              },
            ]}
          />
        ) : <Empty description="暂无复核草稿" />}
      </Card>
    </div>
  );
}
