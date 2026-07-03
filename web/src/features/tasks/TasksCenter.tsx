import type { CSSProperties } from "react";
import { Card, Empty, Table } from "antd";
import type { TableProps } from "antd";
import { UploadForm } from "./UploadForm";
import { JobStatusCell } from "./JobStatusCell";
import { useJobsStore, type SubmittedJob } from "./jobsStore";

const TABLE_LOCALE = { emptyText: <Empty description="暂无作业" /> };

// 任务中心: 上传表单 + 作业队列(每行自行轮询状态)。
export function TasksCenter() {
  const jobs = useJobsStore((s) => s.jobs);

  const columns: TableProps<SubmittedJob>["columns"] = [
    { title: "文件", dataIndex: "filename", key: "filename", ellipsis: true },
    {
      title: "地点",
      dataIndex: "location",
      key: "location",
      render: (v: string | undefined) => v || "-",
    },
    {
      title: "时相",
      dataIndex: "acquisitionTime",
      key: "acq",
      render: (v: string | undefined) => v || "-",
    },
    {
      title: "状态",
      key: "status",
      render: (_: unknown, r: SubmittedJob) => (
        <JobStatusCell jobId={r.jobId} />
      ),
    },
    {
      title: "提交时间",
      dataIndex: "submittedAt",
      key: "submittedAt",
      render: (v: number) => new Date(v).toLocaleString(),
    },
  ];

  return (
    <div style={WRAP}>
      <Card title="发起推理作业">
        <UploadForm />
      </Card>
      <Card title="作业队列">
        <Table<SubmittedJob>
          rowKey="jobId"
          size="small"
          columns={columns}
          dataSource={jobs}
          pagination={false}
          locale={TABLE_LOCALE}
        />
      </Card>
    </div>
  );
}

const WRAP: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 16,
  maxWidth: 900,
};
