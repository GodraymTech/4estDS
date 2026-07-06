import { useEffect, useMemo, useState } from "react";
import type { DragEvent } from "react";
import {
  Button,
  Input,
  InputNumber,
  Progress,
  Select,
  Space,
  Tooltip,
  Upload,
  message,
} from "antd";
import {
  DownOutlined,
  FileImageOutlined,
  FolderOpenOutlined,
  InfoCircleOutlined,
  InboxOutlined,
  PlayCircleOutlined,
  RightOutlined,
  StopOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { ApiError, endpoints, type InferSubmit, type InputInspectResult } from "../../shared/api";
import { useJobsStore } from "./jobsStore";

const EXPORT_OPTIONS = [
  { value: "shp", label: "shp" },
  { value: "geojson", label: "geojson" },
  { value: "gpkg", label: "gpkg" },
  { value: "csv", label: "csv" },
];

const PATH_TIP =
  "支持“图像路径”（单图像推理）和“文件夹路径”（批量推理）";
const LOCATION_TIP =
  '为输入图像设置具有唯一性的"地理标识", 格式通常为【市_县_区块名/编号】, 默认使用"图像文件名"。 如果此次任务为批量推理，您输入的「location」将作为“地理标识前缀”。';

export function UploadForm({
  activeJobId,
  onSubmitted,
  onCancelled,
}: {
  activeJobId?: string;
  onSubmitted?: (jobId: string) => void;
  onCancelled?: (jobId: string) => void;
}) {
  const [inputPath, setInputPath] = useState("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [inspect, setInspect] = useState<InputInspectResult | null>(null);
  const [inspectBusy, setInspectBusy] = useState(false);
  const [location, setLocation] = useState("");
  const [acquisitionTime, setAcquisitionTime] = useState("");
  const [tileSize, setTileSize] = useState<number | null>(null);
  const [overlapPercent, setOverlapPercent] = useState<number | null>(null);
  const [exportFmt, setExportFmt] = useState("shp");
  const [dsmOpen, setDsmOpen] = useState(false);
  const [demOpen, setDemOpen] = useState(false);
  const [lasOpen, setLasOpen] = useState(false);
  const [dsm, setDsm] = useState("");
  const [dem, setDem] = useState("");
  const [las, setLas] = useState("");
  const [progress, setProgress] = useState(0);
  const [busy, setBusy] = useState(false);
  const addJob = useJobsStore((s) => s.addJob);

  useEffect(() => {
    const path = inputPath.trim();
    if (!path) {
      setInspect(null);
      return undefined;
    }
    setUploadFile(null);
    const handle = window.setTimeout(() => {
      void inspectPath(path);
    }, 450);
    return () => window.clearTimeout(handle);
  }, [inputPath]);

  const isBatch = inspect?.input_kind === "directory";
  const suggestedLocation = inspect?.suggested_location || undefined;
  const suggestedDate = inspect?.suggested_acquisition_time || undefined;
  const inputName = useMemo(() => {
    if (inspect?.normalized_path) return basename(inspect.normalized_path);
    if (inputPath.trim()) return basename(inputPath.trim());
    return uploadFile?.name || "";
  }, [inputPath, inspect?.normalized_path, uploadFile?.name]);

  async function inspectPath(path: string) {
    setInspectBusy(true);
    try {
      const res = await endpoints.inspectInput({ input_path: path });
      setInspect(res);
    } catch (e) {
      setInspect(null);
      if (e instanceof ApiError && e.status !== 404) {
        message.warning(e.message);
      }
    } finally {
      setInspectBusy(false);
    }
  }

  async function submit() {
    const body = buildSubmitBody();
    if (!body) return;
    setBusy(true);
    setProgress(0);
    try {
      let finalBody = body;
      if (!body.input_path && uploadFile) {
        const up = await endpoints.uploadImage(uploadFile, setProgress);
        finalBody = { ...body, image_key: up.key };
      }
      const ref = await endpoints.submitInfer(finalBody);
      addJob({
        jobId: ref.job_id,
        filename: inputName || uploadFile?.name || ref.job_id,
        sourceKind: isBatch ? "directory" : body.input_path ? "file" : "upload",
        location: location || suggestedLocation,
        acquisitionTime: acquisitionTime || suggestedDate,
        submittedAt: Date.now(),
      });
      onSubmitted?.(ref.job_id);
      message.success("作业已提交：" + ref.job_id);
      setProgress(0);
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "提交失败");
    } finally {
      setBusy(false);
    }
  }

  async function cancelActiveJob() {
    setBusy(true);
    try {
      const res = await endpoints.cancelAllJobs();
      if (activeJobId) onCancelled?.(activeJobId);
      message.success(res.message);
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "终止失败");
    } finally {
      setBusy(false);
    }
  }

  function buildSubmitBody(): InferSubmit | null {
    const cleanTime = acquisitionTime.replace(/[^\d]/g, "");
    if (acquisitionTime && cleanTime.length !== 8) {
      message.warning("地块生成日期需为 8 位 YYYYMMDD");
      return null;
    }
    if (!inputPath.trim() && !uploadFile) {
      message.warning("请先输入路径或拖入影像文件");
      return null;
    }

    const body: InferSubmit = {
      export_fmt: exportFmt,
    };
    if (inputPath.trim()) body.input_path = inputPath.trim();
    if (cleanTime) body.acquisition_time = cleanTime;
    if (location.trim()) body.location = location.trim();
    if (typeof tileSize === "number") body.tile_size = tileSize;
    if (typeof overlapPercent === "number") body.overlap_rate = overlapPercent / 100;
    if (dsmOpen && dsm.trim()) body.dsm = dsm.trim();
    if (demOpen && dem.trim()) body.dem = dem.trim();
    if (lasOpen && las.trim()) body.las = las.trim();
    return body;
  }

  function handlePathDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    const droppedPath = extractTransferPath(e);
    if (droppedPath) {
      setInputPath(droppedPath);
      return;
    }
    const file = e.dataTransfer.files?.[0];
    if (!file) return;
    setUploadFile(file);
    setInputPath("");
    setInspect(null);
  }

  return (
    <div className="task-form">
      <div className="task-form__section">
        <div className="task-field-row task-field-row--path">
          <FieldLabel title="输入路径" tooltip={PATH_TIP} />
          <div className="task-path-control">
            <Input
              value={inputPath}
              onChange={(e) => setInputPath(e.target.value)}
              placeholder="图像路径或文件夹路径"
              prefix={isBatch ? <FolderOpenOutlined /> : <FileImageOutlined />}
              disabled={busy}
              allowClear
            />
            <Upload
              multiple={false}
              maxCount={1}
              showUploadList={false}
              beforeUpload={(file) => {
                const path = droppedFilePath(file as File & { path?: string });
                if (path) {
                  setInputPath(path);
                  return false;
                }
                setUploadFile(file);
                setInputPath("");
                setInspect(null);
                return false;
              }}
              disabled={busy}
            >
              <Button icon={<UploadOutlined />} disabled={busy}>
                选择
              </Button>
            </Upload>
          </div>
        </div>
        <div className="task-drop-zone" onDragOver={(e) => e.preventDefault()} onDrop={handlePathDrop}>
          <InboxOutlined />
          <span>{uploadFile ? uploadFile.name : "拖入图像、目录路径或本地影像"}</span>
        </div>
        <InputStatus inspect={inspect} busy={inspectBusy} />
      </div>

      <div className="task-form__grid">
        <div className="task-field-row">
          <FieldLabel title="地块生成日期" />
          <Input
            value={acquisitionTime}
            onChange={(e) => setAcquisitionTime(e.target.value)}
            placeholder={suggestedDate ? `默认 ${suggestedDate}` : "默认读取元数据"}
            disabled={busy}
          />
        </div>
        <div className="task-field-row">
          <FieldLabel title="地理标识" tooltip={LOCATION_TIP} />
          <Input
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            placeholder={
              isBatch
                ? "批量时作为前缀"
                : suggestedLocation
                  ? `默认 ${suggestedLocation}`
                  : "默认图像文件名"
            }
            disabled={busy}
          />
        </div>
        <div className="task-field-row">
          <FieldLabel title="切片尺寸" />
          <InputNumber
            value={tileSize}
            onChange={(v) => setTileSize(typeof v === "number" ? v : null)}
            placeholder="默认自适应"
            min={1}
            precision={0}
            disabled={busy}
            className="task-number"
          />
        </div>
        <div className="task-field-row">
          <FieldLabel title="覆盖率" />
          <InputNumber
            value={overlapPercent}
            onChange={(v) => setOverlapPercent(typeof v === "number" ? v : null)}
            placeholder="默认自适应"
            min={0}
            max={50}
            precision={0}
            addonAfter="%"
            disabled={busy}
            className="task-number"
          />
        </div>
        <div className="task-field-row">
          <FieldLabel title="导出格式" />
          <Select
            value={exportFmt}
            onChange={setExportFmt}
            options={EXPORT_OPTIONS}
            disabled={busy}
            className="task-select"
          />
        </div>
      </div>

      <div className="task-form__section task-form__section--aux">
        <OptionalPath title="DSM" open={dsmOpen} value={dsm} onOpen={setDsmOpen} onChange={setDsm} disabled={busy} />
        <OptionalPath title="DEM" open={demOpen} value={dem} onOpen={setDemOpen} onChange={setDem} disabled={busy} />
        <OptionalPath title="LAS" open={lasOpen} value={las} onOpen={setLasOpen} onChange={setLas} disabled={busy} />
      </div>

      {busy && progress > 0 ? <Progress percent={progress} size="small" /> : null}

      <div className="task-action-row">
        <Button
          type="primary"
          icon={<PlayCircleOutlined />}
          loading={busy}
          disabled={!inputPath.trim() && !uploadFile}
          onClick={submit}
          className="task-action-primary"
        >
          开始推理
        </Button>
        <Button
          danger
          type="primary"
          icon={<StopOutlined />}
          disabled={busy}
          onClick={cancelActiveJob}
          className="task-action-danger"
        >
          一键终止
        </Button>
      </div>
    </div>
  );
}

function FieldLabel({ title, tooltip }: { title: string; tooltip?: string }) {
  return (
    <div className="task-label">
      <span>{title}</span>
      {tooltip ? (
        <Tooltip title={tooltip} placement="topLeft">
          <InfoCircleOutlined className="task-label__info" />
        </Tooltip>
      ) : null}
    </div>
  );
}

function OptionalPath({
  title,
  open,
  value,
  onOpen,
  onChange,
  disabled,
}: {
  title: string;
  open: boolean;
  value: string;
  onOpen: (open: boolean) => void;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className={open ? "task-optional task-optional--open" : "task-optional"}>
      <div className="task-field-row">
        <button
          type="button"
          className="task-optional__title"
          onClick={() => onOpen(!open)}
          disabled={disabled}
        >
          {open ? <DownOutlined /> : <RightOutlined />}
          <span>{title}</span>
        </button>
        {open ? (
          <CompactPathInput
            value={value}
            onChange={onChange}
            placeholder={`${title} 路径`}
            disabled={disabled}
          />
        ) : (
          <span className="task-optional__hint">默认不设置</span>
        )}
      </div>
    </div>
  );
}

function CompactPathInput({
  value,
  onChange,
  placeholder,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  disabled?: boolean;
}) {
  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    const transferPath = extractTransferPath(e);
    if (transferPath) {
      onChange(transferPath);
      return;
    }
    const file = e.dataTransfer.files?.[0] as (File & { path?: string }) | undefined;
    applyPickedPath(file, onChange);
  }

  return (
    <div className="task-path-control" onDragOver={(e) => e.preventDefault()} onDrop={handleDrop}>
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        allowClear
      />
      <Upload
        multiple={false}
        maxCount={1}
        showUploadList={false}
        beforeUpload={(file) => {
          applyPickedPath(file as File & { path?: string }, onChange);
          return false;
        }}
        disabled={disabled}
      >
        <Button icon={<UploadOutlined />} disabled={disabled}>
          选择
        </Button>
      </Upload>
    </div>
  );
}

function InputStatus({
  inspect,
  busy,
}: {
  inspect: InputInspectResult | null;
  busy: boolean;
}) {
  if (busy) return <span className="task-input-status">正在读取元数据...</span>;
  if (!inspect) return null;
  const size =
    inspect.images[0]?.width && inspect.images[0]?.height
      ? `${inspect.images[0].width}x${inspect.images[0].height}`
      : "";
  return (
    <Space size={8} wrap className="task-input-status">
      <span>{inspect.input_kind === "directory" ? "批量目录" : "单图影像"}</span>
      <span>{inspect.image_count} 张</span>
      {size ? <span className="mono">{size}</span> : null}
      {inspect.suggested_acquisition_time ? (
        <span className="mono">{inspect.suggested_acquisition_time}</span>
      ) : null}
    </Space>
  );
}

function basename(path: string) {
  return path.replace(/\\/g, "/").split("/").filter(Boolean).pop() || path;
}

function applyPickedPath(
  file: (File & { path?: string }) | undefined,
  onChange: (value: string) => void,
) {
  if (!file) return;
  const path = droppedFilePath(file);
  if (path) {
    onChange(path);
    return;
  }
  message.warning("当前浏览器无法读取真实路径，请手动输入；桌面版拖拽/点选可自动填入。");
}

function extractTransferPath(e: DragEvent<HTMLElement>) {
  const text = e.dataTransfer.getData("text/plain").trim();
  if (text) return normalizeDroppedText(text);
  const uri = e.dataTransfer.getData("text/uri-list").trim();
  if (uri) return normalizeDroppedText(uri.split(/\r?\n/).find((line) => !line.startsWith("#")) || uri);
  const file = e.dataTransfer.files?.[0] as (File & { path?: string }) | undefined;
  return file ? droppedFilePath(file) : null;
}

function droppedFilePath(file: File & { path?: string }) {
  return typeof file.path === "string" && file.path ? file.path : null;
}

function normalizeDroppedText(text: string) {
  const clean = text.trim().replace(/^['"]|['"]$/g, "");
  if (clean.startsWith("file://")) {
    try {
      return normalizeFileUriPath(decodeURIComponent(clean.replace(/^file:\/\//, "")));
    } catch {
      return normalizeFileUriPath(clean.replace(/^file:\/\//, ""));
    }
  }
  return clean;
}

function normalizeFileUriPath(path: string) {
  return /^\/[A-Za-z]:\//.test(path) ? path.slice(1) : path;
}
