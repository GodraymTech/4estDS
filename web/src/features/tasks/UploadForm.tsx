import { useEffect, useState } from "react";
import type { DragEvent } from "react";
import {
    App,
    Button,
    Input,
    InputNumber,
    Progress,
    Select,
    Space,
    Tooltip,
    message as staticMessage,
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
} from "@ant-design/icons";
import { useSearchParams } from "react-router-dom";
import {
    ApiError,
    endpoints,
    type BatchInferItem,
    type InputInspectResult,
} from "../../shared/api";
import { EMPTY_DRAFT, useJobsStore } from "./jobsStore";
import { ServerFileBrowserModal } from "../../shared/ui/ServerFileBrowserModal";

const EXPORT_OPTIONS = [
    { value: "shp", label: "shp" },
    { value: "geojson", label: "geojson" },
    { value: "gpkg", label: "gpkg" },
    { value: "csv", label: "csv" },
];

const TASK_TYPE_OPTIONS = [
    { value: "fast", label: "红树速检" },
    { value: "fine", label: "树种精检" },
];

const TASK_TYPE_TIP = (
    <div style={{ whiteSpace: "pre-line" }}>
        {`- 红树速检：快速检出所有红树林单木及其死亡植株\n- 树种精检：进一步识别出各植株所属种类，当前支持「秋茄、红海榄、桐花树、木榄、白骨壤、无瓣海桑」`}
    </div>
);

const PATH_TIP =
    "仅支持单张 .tif 影像";
const TRACT_TIP =
    "默认为文件名，建议修改为所属「项目名」";

interface FormInferItem extends BatchInferItem {
    displayName: string;
}

export function UploadForm({
    activeJobId,
    onSubmitted,
    onCancelled,
}: {
    activeJobId?: string;
    onSubmitted?: (jobId: string) => void;
    onCancelled?: (jobId: string) => void;
}) {
    const { modal, message } = App.useApp();
    const [searchParams] = useSearchParams();

    const draft = useJobsStore((s) => s.draft);
    const patchDraft = useJobsStore((s) => s.patchDraft);
    const resetDraft = useJobsStore((s) => s.resetDraft);
    const clearDraftInput = useJobsStore((s) => s.clearDraftInput);
    const addJob = useJobsStore((s) => s.addJob);

    // File 对象无法持久化，留在本地状态。
    const [uploadFile, setUploadFile] = useState<File | null>(null);
    const [inspect, setInspect] = useState<InputInspectResult | null>(null);
    const [inspectBusy, setInspectBusy] = useState(false);
    const [busy, setBusy] = useState(false);
    const [progress, setProgress] = useState(0);

    const [browserOpen, setBrowserOpen] = useState(false);
    const [browserConfig, setBrowserConfig] = useState<{
        value: string;
        onChange: (val: string) => void;
        title: string;
        selectType: "file" | "dir" | "both";
    } | null>(null);

    const openBrowser = (
        value: string,
        onChange: (val: string) => void,
        title: string,
        selectType: "file" | "dir" | "both" = "file"
    ) => {
        setBrowserConfig({ value, onChange, title, selectType });
        setBrowserOpen(true);
    };

    useEffect(() => {
        const nextInputPath = searchParams.get("input_path")?.trim() || "";
        const nextTractId = searchParams.get("tract_id")?.trim() || "";
        const nextPhaseId = searchParams.get("phase_id")?.trim() || "";

        if (nextInputPath || nextTractId || nextPhaseId) {
            patchDraft({
                ...EMPTY_DRAFT,
                ...(nextInputPath ? { inputPath: nextInputPath } : {}),
                ...(nextTractId ? { tractId: nextTractId } : {}),
                ...(nextPhaseId ? { phaseId: nextPhaseId } : {}),
            });
        } else {
            resetDraft();
        }
    }, [patchDraft, resetDraft, searchParams]);

    useEffect(() => {
        const path = draft.inputPath.trim();
        if (!path) {
            setInspect(null);
            return undefined;
        }
        setUploadFile(null);
        const handle = window.setTimeout(() => {
            void inspectPath(path);
        }, 450);
        return () => window.clearTimeout(handle);
    }, [draft.inputPath]);

    const isBatch = inspect?.input_kind === "directory";
    const suggestedTractId = inspect?.suggested_tract_id || undefined;
    const suggestedPhaseId = inspect?.suggested_phase_id || undefined;
    const hasInput = Boolean(draft.inputPath.trim() || uploadFile);

    // 本次提交将要执行的条数
    const runCount = hasInput ? (isBatch ? inspect?.images.length || 1 : 1) : 0;

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

    /** 把当前表单构造成待提交的推理条目列表。 */
    async function buildItemsFromForm(): Promise<FormInferItem[] | null> {
        const cleanPhaseId = draft.phaseId.replace(/[^\d]/g, "");
        if (draft.phaseId && cleanPhaseId.length !== 8) {
            message.warning("时相 ID 需为 8 位 YYYYMMDD");
            return null;
        }
        if (!hasInput) {
            message.warning("请先输入路径或拖入影像文件");
            return null;
        }

        const shared = {
            task_type: draft.taskType || "fast",
            phase_id: cleanPhaseId || undefined,
            tile_size: typeof draft.tileSize === "number" ? draft.tileSize : undefined,
            overlap_rate:
                typeof draft.overlapPercent === "number" ? draft.overlapPercent / 100 : undefined,
            dsm: draft.dsmOpen && draft.dsm.trim() ? draft.dsm.trim() : undefined,
            dem: draft.demOpen && draft.dem.trim() ? draft.dem.trim() : undefined,
            las: draft.lasOpen && draft.las.trim() ? draft.las.trim() : undefined,
            export_fmt: draft.exportFmt,
        };
        const tractId = draft.tractId.trim() || undefined;

        // 本地上传文件
        if (uploadFile && !draft.inputPath.trim()) {
            const up = await endpoints.uploadImage(uploadFile, setProgress);
            return [
                {
                    image_key: up.key,
                    displayName: uploadFile.name,
                    tract_id: tractId,
                    ...shared,
                },
            ];
        }

        const rawPath = draft.inputPath.trim();
        if (isBatch) {
            const images = inspect?.images ?? [];
            if (!images.length) {
                message.warning("该目录下没有可用的影像文件");
                return null;
            }
            if (inspect && inspect.image_count > images.length) {
                message.warning(
                    `目录内共 ${inspect.image_count} 张影像，本次将提交前 ${images.length} 张`
                );
            }
            if (tractId) {
                message.info("目录展开为多张影像，地块 ID 将按各自文件名生成");
            }
            return images.map((img) => ({
                input_path: img.path,
                displayName: basename(img.path),
                tract_id: undefined,
                ...shared,
            }));
        }

        const filePath = inspect?.normalized_path || rawPath;
        return [
            {
                input_path: filePath,
                displayName: basename(filePath),
                tract_id: tractId,
                ...shared,
            },
        ];
    }

    function resetInput() {
        clearDraftInput();
        setUploadFile(null);
        setInspect(null);
        setProgress(0);
    }

    async function submit() {
        setBusy(true);
        try {
            const items = await buildItemsFromForm();
            if (!items || !items.length) return;

            let firstJobId: string | undefined;
            for (const item of items) {
                const { displayName, ...payload } = item;
                const ref = await endpoints.submitBatch({
                    items: [payload],
                });
                if (!firstJobId) firstJobId = ref.job_id;
                addJob({
                    jobId: ref.job_id,
                    filename: displayName,
                    fullPath: item.input_path,
                    taskType: item.task_type,
                    tractId: item.tract_id,
                    phaseId: item.phase_id,
                    tileSize: item.tile_size ?? null,
                    overlapPercent:
                        typeof item.overlap_rate === "number"
                            ? Math.round(item.overlap_rate * 100)
                            : null,
                    submittedAt: Date.now(),
                });
            }
            resetInput();
            if (firstJobId) onSubmitted?.(firstJobId);
            message.success(
                items.length === 1
                    ? `作业已提交：${items[0].displayName}`
                    : `已提交 ${items.length} 个推理作业`
            );
        } catch (e) {
            message.error(e instanceof ApiError ? e.message : "提交失败");
        } finally {
            setBusy(false);
        }
    }

    function cancelActiveJob() {
        modal.confirm({
            title: "终止全部推理作业",
            content:
                "已完成的影像保留为「成功」，正在推理的记为「失败」，尚未开始的记为「已取消」。",
            okText: "终止",
            okButtonProps: { danger: true },
            cancelText: "取消",
            onOk: async () => {
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
            },
        });
    }

    function handlePathDrop(e: DragEvent<HTMLDivElement>) {
        e.preventDefault();
        const droppedPath = extractTransferPath(e);
        if (droppedPath) {
            patchDraft({ inputPath: droppedPath });
            return;
        }
        const file = e.dataTransfer.files?.[0];
        if (!file) return;
        setUploadFile(file);
        clearDraftInput();
        setInspect(null);
    }

    return (
        <div className="task-form">
            <div className="task-form__section">
                <div className="task-field-row task-field-row--path">
                    <FieldLabel title="输入路径" tooltip={PATH_TIP} />
                    <div className="task-path-control">
                        <Input
                            value={draft.inputPath}
                            onChange={(e) => patchDraft({ inputPath: e.target.value })}
                            placeholder="图像路径"
                            prefix={isBatch ? <FolderOpenOutlined /> : <FileImageOutlined />}
                            disabled={busy}
                            allowClear
                        />
                        <Button
                            icon={<FolderOpenOutlined />}
                            disabled={busy}
                            onClick={() =>
                                openBrowser(
                                    draft.inputPath,
                                    (val) => patchDraft({ inputPath: val }),
                                    "选择输入路径 (影像文件或目录)",
                                    "both"
                                )
                            }
                        >
                            选择
                        </Button>
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
                    <FieldLabel title="任务类型" tooltip={TASK_TYPE_TIP} />
                    <Select
                        value={draft.taskType}
                        onChange={(v) => patchDraft({ taskType: v })}
                        options={TASK_TYPE_OPTIONS}
                        disabled={busy}
                        className="task-select"
                    />
                </div>
                <div className="task-field-row">
                    <FieldLabel title="导出格式" />
                    <Select
                        value={draft.exportFmt}
                        onChange={(v) => patchDraft({ exportFmt: v })}
                        options={EXPORT_OPTIONS}
                        disabled={busy}
                        className="task-select"
                    />
                </div>
                <div className="task-field-row">
                    <FieldLabel title="时相 ID" />
                    <Input
                        value={draft.phaseId}
                        onChange={(e) => patchDraft({ phaseId: e.target.value })}
                        placeholder={suggestedPhaseId ? `默认 ${suggestedPhaseId}` : "自动"}
                        disabled={busy}
                    />
                </div>
                <div className="task-field-row">
                    <FieldLabel title="地块 ID" tooltip={TRACT_TIP} />
                    <Input
                        value={draft.tractId}
                        onChange={(e) => patchDraft({ tractId: e.target.value })}
                        placeholder={
                            isBatch
                                ? "目录展开后按文件名生成"
                                : suggestedTractId
                                    ? `默认 ${suggestedTractId}`
                                    : "自动"
                        }
                        disabled={busy || isBatch}
                    />
                </div>
                <div className="task-field-row">
                    <FieldLabel title="切片尺寸" />
                    <InputNumber
                        value={draft.tileSize}
                        onChange={(v) => patchDraft({ tileSize: typeof v === "number" ? v : null })}
                        placeholder="自适应"
                        min={1}
                        precision={0}
                        disabled={busy}
                        className="task-number"
                    />
                </div>
                <div className="task-field-row">
                    <FieldLabel title="重叠率" />
                    <InputNumber
                        value={draft.overlapPercent}
                        onChange={(v) => patchDraft({ overlapPercent: typeof v === "number" ? v : null })}
                        placeholder="自适应"
                        min={0}
                        max={50}
                        precision={0}
                        addonAfter="%"
                        disabled={busy}
                        className="task-number"
                    />
                </div>
            </div>

            <div className="task-form__section task-form__section--aux">
                <OptionalPath
                    title="DSM"
                    open={draft.dsmOpen}
                    value={draft.dsm}
                    onOpen={(open) => patchDraft({ dsmOpen: open })}
                    onChange={(val) => patchDraft({ dsm: val })}
                    disabled={busy}
                    onSelectClick={() =>
                        openBrowser(draft.dsm, (val) => patchDraft({ dsm: val }), "选择 DSM 路径", "file")
                    }
                />
                <OptionalPath
                    title="DEM"
                    open={draft.demOpen}
                    value={draft.dem}
                    onOpen={(open) => patchDraft({ demOpen: open })}
                    onChange={(val) => patchDraft({ dem: val })}
                    disabled={busy}
                    onSelectClick={() =>
                        openBrowser(draft.dem, (val) => patchDraft({ dem: val }), "选择 DEM 路径", "file")
                    }
                />
                <OptionalPath
                    title="LAS"
                    open={draft.lasOpen}
                    value={draft.las}
                    onOpen={(open) => patchDraft({ lasOpen: open })}
                    onChange={(val) => patchDraft({ las: val })}
                    disabled={busy}
                    onSelectClick={() =>
                        openBrowser(draft.las, (val) => patchDraft({ las: val }), "选择 LAS 路径", "file")
                    }
                />
            </div>

            {browserConfig && (
                <ServerFileBrowserModal
                    open={browserOpen}
                    onClose={() => {
                        setBrowserOpen(false);
                        setBrowserConfig(null);
                    }}
                    onSelect={browserConfig.onChange}
                    selectType={browserConfig.selectType}
                    title={browserConfig.title}
                    defaultPath={browserConfig.value}
                />
            )}

            {busy && progress > 0 ? <Progress percent={progress} size="small" /> : null}

            <div className="task-action-row">
                <Tooltip title={runCount > 0 ? `开始推理 (${runCount} 张影像)` : "开始推理"}>
                    <Button
                        type="primary"
                        icon={<PlayCircleOutlined />}
                        loading={busy}
                        disabled={runCount === 0}
                        onClick={submit}
                        className="task-action-btn task-action-btn--primary"
                        aria-label="开始推理"
                    >
                        {runCount > 0 ? <span className="task-action-badge">{runCount}</span> : null}
                    </Button>
                </Tooltip>
                <Tooltip title="一键终止">
                    <Button
                        danger
                        icon={<StopOutlined />}
                        disabled={busy}
                        onClick={cancelActiveJob}
                        className="task-action-btn task-action-btn--danger"
                        aria-label="一键终止全部作业"
                    />
                </Tooltip>
            </div>
        </div>
    );
}

function FieldLabel({ title, tooltip }: { title: string; tooltip?: React.ReactNode }) {
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
    onSelectClick,
}: {
    title: string;
    open: boolean;
    value: string;
    onOpen: (open: boolean) => void;
    onChange: (value: string) => void;
    disabled?: boolean;
    onSelectClick: () => void;
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
                        onSelectClick={onSelectClick}
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
    onSelectClick,
}: {
    value: string;
    onChange: (value: string) => void;
    placeholder: string;
    disabled?: boolean;
    onSelectClick: () => void;
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
            <Button icon={<FolderOpenOutlined />} disabled={disabled} onClick={onSelectClick}>
                选择
            </Button>
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
            {inspect.suggested_phase_id ? (
                <span className="mono">{inspect.suggested_phase_id}</span>
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
    staticMessage.warning("当前浏览器无法读取真实路径，请手动输入；桌面版拖拽/点选可自动填入。");
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
