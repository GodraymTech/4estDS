import { useState } from "react";
import type { CSSProperties } from "react";
import {
  Button,
  DatePicker,
  Input,
  Progress,
  Select,
  Space,
  Upload,
  message,
} from "antd";
import { InboxOutlined } from "@ant-design/icons";
import type { UploadFile } from "antd";
import { ApiError, endpoints } from "../../shared/api";
import { useJobsStore } from "./jobsStore";

const ARCH_OPTIONS = [
  { value: "yolo26x", label: "yolo26x（默认）" },
  { value: "yolo26l", label: "yolo26l" },
  { value: "yolo26m", label: "yolo26m" },
];

// 发起推理作业: 选影像 → 上传(带进度) → 提交 /jobs/infer → 入队。
export function UploadForm() {
  const [file, setFile] = useState<File | null>(null);
  const [location, setLocation] = useState("");
  const [acq, setAcq] = useState("");
  const [arch, setArch] = useState("yolo26x");
  const [progress, setProgress] = useState(0);
  const [busy, setBusy] = useState(false);
  const addJob = useJobsStore((s) => s.addJob);

  const submit = async () => {
    if (!file) {
      message.warning("请先选择影像文件");
      return;
    }
    setBusy(true);
    setProgress(0);
    try {
      const up = await endpoints.uploadImage(file, setProgress);
      const ref = await endpoints.submitInfer({
        image_key: up.key,
        arch,
        acquisition_time: acq ? acq.replace(/-/g, "") : undefined,
        location: location || undefined,
      });
      addJob({
        jobId: ref.job_id,
        filename: up.filename,
        location: location || undefined,
        acquisitionTime: acq || undefined,
        submittedAt: Date.now(),
      });
      message.success("作业已提交：" + ref.job_id);
      setFile(null);
      setLocation("");
      setAcq("");
      setProgress(0);
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "提交失败");
    } finally {
      setBusy(false);
    }
  };

  const fileList: UploadFile[] = file
    ? [{ uid: "-1", name: file.name, status: "done" }]
    : [];

  return (
    <Space direction="vertical" size={12} style={FULL}>
      <Upload.Dragger
        multiple={false}
        maxCount={1}
        fileList={fileList}
        beforeUpload={(f) => {
          setFile(f);
          return false;
        }}
        onRemove={() => setFile(null)}
        disabled={busy}
      >
        <p style={ICON}>
          <InboxOutlined />
        </p>
        <p>点击或拖拽影像到此处上传</p>
        <p style={HINT}>支持单个 GeoTIFF 大图(服务端窗口化推理)</p>
      </Upload.Dragger>

      <Space wrap>
        <Select
          value={arch}
          onChange={setArch}
          options={ARCH_OPTIONS}
          style={SEL}
          disabled={busy}
        />
        <DatePicker
          placeholder="时相日期"
          onChange={(_, ds) => setAcq(typeof ds === "string" ? ds : "")}
          disabled={busy}
        />
        <Input
          placeholder="地点(选填)"
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          style={SEL}
          disabled={busy}
        />
      </Space>

      {busy ? <Progress percent={progress} size="small" /> : null}

      <Button type="primary" loading={busy} disabled={!file} onClick={submit}>
        提交推理作业
      </Button>
    </Space>
  );
}

const FULL: CSSProperties = { width: "100%" };
const SEL: CSSProperties = { width: 200 };
const ICON: CSSProperties = {
  fontSize: 32,
  color: "var(--color-primary, #0e6e63)",
};
const HINT: CSSProperties = {
  fontSize: 12,
  color: "var(--color-text-muted, #5c6b66)",
};
