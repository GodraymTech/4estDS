import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Checkbox, InputNumber, Segmented, Select, Slider, Space, Switch, Tag, Tooltip, Typography, message } from "antd";
import { InfoCircleOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { ReviewAttempt, ReviewCategory, ReviewItem } from "../../entities/review";
import { endpoints, type ReviewMapContext } from "../../shared/api";
import { useReviewWorkbenchStore, MIN_REGION_SIDE_PX } from "./store";

export function PromptPanel({ sessionId, revision, categories, items, mapContext, getCenterPx, onCreated }: {
  sessionId: string;
  revision: number;
  categories: ReviewCategory[];
  items: ReviewItem[];
  mapContext: ReviewMapContext;
  getCenterPx: () => [number, number] | null;
  onCreated: (attempt: ReviewAttempt) => void;
}) {
  const capabilities = useQuery({ queryKey: ["review-capabilities"], queryFn: endpoints.getReviewCapabilities });
  const activeTool = useReviewWorkbenchStore((state) => state.activeTool);
  const regionSidePx = useReviewWorkbenchStore((state) => state.regionSidePx);
  const setRegionSidePx = useReviewWorkbenchStore((state) => state.setRegionSidePx);
  const regionMetricsVisible = useReviewWorkbenchStore((state) => state.regionMetricsVisible);
  const setRegionMetricsVisible = useReviewWorkbenchStore((state) => state.setRegionMetricsVisible);
  const mergeMode = useReviewWorkbenchStore((state) => state.mergeMode);
  const setMergeMode = useReviewWorkbenchStore((state) => state.setMergeMode);
  const autoTrigger = useReviewWorkbenchStore((state) => state.autoTrigger);
  const setAutoTrigger = useReviewWorkbenchStore((state) => state.setAutoTrigger);
  const [selectedCategories, setSelectedCategories] = useState<string[]>([]);
  const [exemplarIds, setExemplarIds] = useState<string[]>([]);
  const [threshold, setThreshold] = useState(0.25);
  const [manualInput, setManualInput] = useState(false);
  const configured = useRef(false);
  const autoSignature = useRef("");

  const promptType = activeTool === "ai_visual" ? "visual" : "text";
  const open = activeTool === "ai_text" || activeTool === "ai_visual";
  const maxSide = Math.max(MIN_REGION_SIDE_PX, mapContext.pixel_width, mapContext.pixel_height);
  const sliderPosition = regionSidePx >= maxSide ? 100 : sideToSlider(regionSidePx, maxSide);
  const isFull = sliderPosition >= 99.8;
  const selected = useMemo(() => categories.filter((item) => selectedCategories.includes(item.id)), [categories, selectedCategories]);
  const exemplars = useMemo(() => items.filter((item) => exemplarIds.includes(item.id)), [items, exemplarIds]);
  const valid = promptType === "text" ? selected.length > 0 : exemplars.length > 0;

  useEffect(() => {
    if (!categories.length) return;
    setSelectedCategories((current) => current.length ? current.filter((id) => categories.some((category) => category.id === id)) : categories.map((category) => category.id));
  }, [categories]);

  useEffect(() => {
    if (!capabilities.data || configured.current) return;
    configured.current = true;
    setMergeMode(capabilities.data.defaults.merge_mode);
    setThreshold(capabilities.data.defaults.threshold);
  }, [capabilities.data, setMergeMode]);

  const create = useMutation({
    mutationFn: () => {
      const center = getCenterPx();
      if (!center && !isFull) throw new Error("地图尚未准备完成，请稍后再试");
      return endpoints.createReviewAttempt(sessionId, {
        revision,
        prompt_type: promptType,
        prompts: selected.map((item) => ({ category_id: item.id, display_name: item.display_name, model_prompt: item.model_prompt })),
        visual_exemplars: exemplars.map((item) => ({ item_id: item.id, category_id: item.species, box_px: item.box_px })),
        scope: isFull ? { type: "full" } : { type: "region", center_px: center as [number, number], side_px: regionSidePx },
        merge_mode: mergeMode,
        threshold,
      });
    },
    onSuccess: (attempt) => {
      onCreated(attempt);
      message.success("AI 识别任务已排队");
    },
    onError: (error) => message.error(error instanceof Error ? error.message : "创建识别任务失败"),
  });

  useEffect(() => {
    if (!open || !autoTrigger || !valid || create.isPending) return;
    const signature = JSON.stringify([promptType, selectedCategories, exemplarIds, isFull, Math.round(regionSidePx), mergeMode, threshold]);
    if (signature === autoSignature.current) return;
    const timer = window.setTimeout(() => {
      autoSignature.current = signature;
      create.mutate();
    }, 850);
    return () => window.clearTimeout(timer);
  }, [open, autoTrigger, valid, promptType, selectedCategories, exemplarIds, isFull, regionSidePx, mergeMode, threshold]);

  if (!open) return null;

  const meterSide = regionSidePx * mapContext.gsd;
  return (
    <section className="review-ai-panel" aria-label="AI 辅助设置">
      <header className="review-ai-panel__header">
        <div>
          <Typography.Text strong>{promptType === "text" ? "文本 Prompt" : "视觉 Prompt"}</Typography.Text>
          <Typography.Text type="secondary">AI 辅助设置</Typography.Text>
        </div>
        <Space size={6}>
          {capabilities.data?.segmentation ? <Tag bordered={false}>实例分割</Tag> : null}
          <Tooltip title="开启后，Prompt 或识别范围变化会自动提交；关闭后使用底部执行按钮。">
            <InfoCircleOutlined />
          </Tooltip>
          <Switch size="small" checked={autoTrigger} onChange={setAutoTrigger} />
          <Typography.Text style={{ fontSize: 12 }}>自动触发</Typography.Text>
        </Space>
      </header>

      {capabilities.data?.available === false ? <Alert type="warning" showIcon message="模型文件不可用" /> : null}

      {promptType === "text" ? (
        <Checkbox.Group
          className="review-prompt-options"
          value={selectedCategories}
          options={categories.map((item) => ({ value: item.id, label: item.display_name }))}
          onChange={(value) => setSelectedCategories(value as string[])}
        />
      ) : (
        <Select
          mode="multiple"
          value={exemplarIds}
          placeholder="选择已接受的参考框"
          options={items.filter((item) => item.status === "accepted" && item.species).map((item) => ({ value: item.id, label: `${item.species} · #${item.id.slice(-6)}` }))}
          onChange={setExemplarIds}
          style={{ width: "100%" }}
        />
      )}

      <div className="review-ai-panel__row">
        <div className="review-ai-panel__label">
          <span>写入模式</span>
          <Tooltip title="推理检测框写入工作集的方式：只追加新识别到的，或全量替换旧工作集。"><InfoCircleOutlined /></Tooltip>
        </div>
        <Segmented
          className="review-merge-segmented"
          size="small"
          value={mergeMode}
          options={[{ value: "append", label: "追加" }, { value: "replace_all", label: "替换" }]}
          onChange={(value) => setMergeMode(value as "append" | "replace_all")}
        />
      </div>

      <div className="review-scope-control">
        <div className="review-ai-panel__label">
          <span>识别范围</span>
          <Button type="text" size="small" onClick={() => setManualInput((value) => !value)}>输入</Button>
          <Button type="text" size="small" onClick={() => setRegionMetricsVisible(!regionMetricsVisible)}>{regionMetricsVisible ? "隐藏框" : "显示框"}</Button>
        </div>
        <div className="review-scope-control__slider">
          <span>{(MIN_REGION_SIDE_PX * mapContext.gsd).toFixed(1)} m</span>
          <Slider
            min={0}
            max={100}
            step={0.1}
            value={sliderPosition}
            tooltip={{ formatter: (value) => Number(value) >= 99.8 ? "全图" : `${meterSide.toFixed(1)} m` }}
            onChange={(value) => setRegionSidePx(value >= 99.8 ? maxSide : sliderToSide(value, maxSide))}
          />
          <span>全图</span>
        </div>
        {manualInput ? (
          <InputNumber
            min={MIN_REGION_SIDE_PX * mapContext.gsd}
            max={maxSide * mapContext.gsd}
            precision={1}
            addonAfter="m"
            value={Number(meterSide.toFixed(1))}
            onChange={(value) => setRegionSidePx(Math.min(maxSide, Math.max(MIN_REGION_SIDE_PX, Number(value ?? meterSide) / Math.max(mapContext.gsd, 1e-9))))}
            style={{ width: 160 }}
          />
        ) : null}
      </div>

      {regionSidePx > 2048 && !isFull ? (
        <Alert type="warning" showIcon message={`当前识别范围较大（${meterSide.toFixed(1)} m），推理耗时将显著增加`} />
      ) : null}

      <div className="review-ai-panel__footer">
        <Space size={8}>
          <Typography.Text type="secondary">置信度</Typography.Text>
          <InputNumber min={0} max={1} step={0.05} precision={2} value={threshold} onChange={(value) => setThreshold(Number(value ?? 0.25))} />
        </Space>
        {!autoTrigger ? (
          <Button type="primary" icon={<ThunderboltOutlined />} loading={create.isPending} disabled={!valid} onClick={() => create.mutate()}>执行识别</Button>
        ) : <Typography.Text type="secondary" style={{ fontSize: 12 }}>{create.isPending ? "正在提交…" : "配置变更后自动执行"}</Typography.Text>}
      </div>
    </section>
  );
}

function sliderToSide(position: number, maxSide: number) {
  return MIN_REGION_SIDE_PX * Math.pow(maxSide / MIN_REGION_SIDE_PX, position / 100);
}

function sideToSlider(side: number, maxSide: number) {
  if (maxSide <= MIN_REGION_SIDE_PX) return 100;
  return Math.max(0, Math.min(100, Math.log(side / MIN_REGION_SIDE_PX) / Math.log(maxSide / MIN_REGION_SIDE_PX) * 100));
}
