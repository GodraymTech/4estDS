import { useEffect, useMemo, useState } from "react";
import { Button, Input, Segmented, Select, Slider, Space, Switch, Tag, Tooltip, message } from "antd";
import {
  AimOutlined,
  EyeInvisibleOutlined,
  EyeOutlined,
  InfoCircleOutlined,
  PlusOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { ReviewAttempt, ReviewCategory, ReviewItem } from "../../entities/review";
import { endpoints, queryKeys, type ReviewMapContext } from "../../shared/api";
import { useReviewWorkbenchStore, MIN_REGION_SIDE_PX } from "./store";

export function PromptPanel({
  sessionId,
  revision,
  categories,
  items,
  mapContext,
  getCenterPx,
  onCreated,
  visualBoxSample,
  onClearVisualSample,
}: {
  sessionId: string;
  revision: number;
  categories: ReviewCategory[];
  items: ReviewItem[];
  mapContext: ReviewMapContext;
  getCenterPx: () => [number, number] | null;
  onCreated: (attempt: ReviewAttempt) => void;
  visualBoxSample?: number[] | null;
  onClearVisualSample?: () => void;
}) {
  const client = useQueryClient();
  const activeTool = useReviewWorkbenchStore((state) => state.activeTool);
  const selectedIds = useReviewWorkbenchStore((state) => state.selectedIds);
  const regionSidePx = useReviewWorkbenchStore((state) => state.regionSidePx);
  const setRegionSidePx = useReviewWorkbenchStore((state) => state.setRegionSidePx);
  const regionMetricsVisible = useReviewWorkbenchStore((state) => state.regionMetricsVisible);
  const setRegionMetricsVisible = useReviewWorkbenchStore((state) => state.setRegionMetricsVisible);
  const mergeMode = useReviewWorkbenchStore((state) => state.mergeMode);
  const setMergeMode = useReviewWorkbenchStore((state) => state.setMergeMode);
  const autoTrigger = useReviewWorkbenchStore((state) => state.autoTrigger);
  const setAutoTrigger = useReviewWorkbenchStore((state) => state.setAutoTrigger);
  const latestRevision = useReviewWorkbenchStore((state) => state.revision);

  // 文本 Prompt: 自定义输入项 + 勾选的已有树种（默认全不选）
  const [customTextPrompts, setCustomTextPrompts] = useState<string[]>([]);
  const [customInputText, setCustomInputText] = useState("");
  const [selectedCategoryIds, setSelectedCategoryIds] = useState<string[]>([]);

  // 视觉 Prompt: 选中的已有框 ID 或直接在地图上手绘的样例框
  const [visualExemplarIds, setVisualExemplarIds] = useState<string[]>([]);
  const [targetSpecies, setTargetSpecies] = useState<string>(categories[0]?.id || "");
  const [drawnSampleBoxes, setDrawnSampleBoxes] = useState<Array<{ id: string; box_px: number[] }>>([]);

  const [threshold, setThreshold] = useState(0.25);

  const promptType = activeTool === "ai_visual" ? "visual" : "text";
  const open = activeTool === "ai_text" || activeTool === "ai_visual";
  const maxSide = Math.max(MIN_REGION_SIDE_PX, mapContext.pixel_width, mapContext.pixel_height);
  const sliderPosition = regionSidePx >= maxSide ? 100 : sideToSlider(regionSidePx, maxSide);
  const isFull = sliderPosition >= 99.8;

  // 模式切换时自适应置信度初始值（视觉 Prompt 零样本分数通常在 0.02~0.15 之间）
  useEffect(() => {
    if (activeTool === "ai_visual") {
      setThreshold((prev) => (prev === 0.25 ? 0.05 : prev));
    } else if (activeTool === "ai_text") {
      setThreshold((prev) => (prev === 0.05 ? 0.25 : prev));
    }
  }, [activeTool]);

  // 捕获外部在地图上直接画下的视觉 Prompt 框（单一样本模式：直接设为当前样本）
  useEffect(() => {
    if (visualBoxSample && visualBoxSample.length === 4) {
      const sampleId = `sample_${Date.now()}`;
      setDrawnSampleBoxes([{ id: sampleId, box_px: visualBoxSample }]);
      setVisualExemplarIds([]);
      onClearVisualSample?.();
      message.success("已捕获当前视觉单木样例");
    }
  }, [visualBoxSample, onClearVisualSample]);

  useEffect(() => {
    if (categories.length && (!targetSpecies || !categories.some((c) => c.id === targetSpecies))) {
      setTargetSpecies(categories[0]?.id || "");
    }
  }, [categories, targetSpecies]);

  // 组合文本 Prompts
  const combinedTextPrompts = useMemo(() => {
    const fromCategories = categories
      .filter((c) => selectedCategoryIds.includes(c.id))
      .map((c) => ({ category_id: c.id, display_name: c.display_name, model_prompt: c.model_prompt || c.display_name }));
    const fromCustom = customTextPrompts.map((text) => ({
      category_id: text,
      display_name: text,
      model_prompt: text,
    }));
    return [...fromCategories, ...fromCustom];
  }, [categories, selectedCategoryIds, customTextPrompts]);

  // 组合视觉样例：单一目标样本模式
  const allVisualExemplars = useMemo(() => {
    const fromExisting = items
      .filter((item) => visualExemplarIds.includes(item.id) && item.box_px?.length === 4)
      .map((item) => ({
        item_id: item.id,
        category_id: targetSpecies || item.species,
        box_px: item.box_px,
      }));
    const fromDrawn = drawnSampleBoxes.map((sample) => ({
      item_id: sample.id,
      category_id: targetSpecies || categories[0]?.id || "tree",
      box_px: sample.box_px,
    }));
    return [...fromExisting, ...fromDrawn].slice(-1);
  }, [items, visualExemplarIds, drawnSampleBoxes, targetSpecies, categories]);

  const hasValidInputs = promptType === "text" ? combinedTextPrompts.length > 0 : allVisualExemplars.length > 0;

  const handleAddCustomText = () => {
    const trimmed = customInputText.trim();
    if (trimmed && !customTextPrompts.includes(trimmed)) {
      setCustomTextPrompts((prev) => [...prev, trimmed]);
      setCustomInputText("");
    }
  };

  const handleAdoptSelectedBox = () => {
    if (!selectedIds.length) {
      message.info("请先在画布上选中一个检测框");
      return;
    }
    const validBoxes = items.filter((item) => selectedIds.includes(item.id) && item.box_px?.length === 4);
    if (!validBoxes.length) {
      message.warning("选中的对象缺少矩形几何");
      return;
    }
    setVisualExemplarIds([validBoxes[0].id]);
    setDrawnSampleBoxes([]);
    message.success("已采纳选中框作为视觉样例");
  };

  const create = useMutation({
    mutationFn: () => {
      const center = getCenterPx();
      if (!center && !isFull) throw new Error("地图正在准备中，请稍候");
      return endpoints.createReviewAttempt(sessionId, {
        revision: latestRevision ?? revision,
        prompt_type: promptType,
        prompts: combinedTextPrompts,
        visual_exemplars: allVisualExemplars,
        scope: isFull ? { type: "full" } : { type: "region", center_px: center as [number, number], side_px: regionSidePx },
        merge_mode: mergeMode,
        threshold,
      });
    },
    onSuccess: (attempt) => {
      onCreated(attempt);
      message.success("AI 识别已启动");
    },
    onError: (error) => {
      void client.invalidateQueries({ queryKey: queryKeys.reviewWorkspace(sessionId) });
      message.error(error instanceof Error ? error.message : "创建任务失败");
    },
  });

  // 视觉画框或参数变更后自动触发（若开启了 autoTrigger）
  useEffect(() => {
    if (!open || !autoTrigger || !hasValidInputs || create.isPending) return;
    const timer = window.setTimeout(() => {
      create.mutate();
    }, 600);
    return () => window.clearTimeout(timer);
  }, [open, autoTrigger, hasValidInputs, promptType, combinedTextPrompts.length, allVisualExemplars.length, regionSidePx, threshold, mergeMode]);

  const [isComposing, setIsComposing] = useState(false);

  if (!open) return null;

  const meterSide = regionSidePx * mapContext.gsd;

  return (
    <div
      className="review-ai-dock"
      role="region"
      aria-label="AI辅助控制面板"
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
    >
      {/* 文本模式：无 title，输入树种在输入框左侧，无 placeholder */}
      {promptType === "text" ? (
        <div className="review-ai-block">
          <div className="review-ai-row">
            <div className="review-ai-inline-label">
              <span>输入树种</span>
              <Tooltip title="可任意指定树种">
                <InfoCircleOutlined style={{ color: "var(--review-muted)" }} />
              </Tooltip>
            </div>
            <Input
              size="middle"
              className="review-ai-main-input"
              value={customInputText}
              onChange={(e) => setCustomInputText(e.target.value)}
              onCompositionStart={() => setIsComposing(true)}
              onCompositionEnd={(e) => {
                setIsComposing(false);
                setCustomInputText(e.currentTarget.value);
              }}
              onPressEnter={(e) => {
                if (isComposing) return;
                e.preventDefault();
                handleAddCustomText();
              }}
              style={{ flex: 1 }}
            />
            <Button
              type="primary"
              size="middle"
              icon={<PlusOutlined />}
              disabled={!customInputText.trim()}
              onClick={handleAddCustomText}
              style={{ flexShrink: 0 }}
              title="添加树种"
            />
          </div>

          {/* 快捷点选已有树种（默认全不选，点选即发光） */}
          {categories.length ? (
            <div className="review-ai-chip-group">
              <div className="review-ai-chip-group__list">
                {categories.map((cat) => {
                  const isChecked = selectedCategoryIds.includes(cat.id);
                  return (
                    <button
                      key={cat.id}
                      type="button"
                      className={`review-ai-chip${isChecked ? " is-checked" : ""}`}
                      onClick={() => {
                        setSelectedCategoryIds((prev) =>
                          isChecked ? prev.filter((id) => id !== cat.id) : [...prev, cat.id],
                        );
                      }}
                    >
                      <span className="review-ai-chip__dot" style={{ backgroundColor: cat.color }} />
                      <span>{cat.display_name}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}

          {/* 已添加的目标 Tag 徽章 */}
          {combinedTextPrompts.length ? (
            <div className="review-ai-tags-box">
              <Space size={[4, 4]} wrap>
                {combinedTextPrompts.map((p) => (
                  <Tag
                    key={p.display_name}
                    closable
                    color="cyan"
                    onClose={() => {
                      setSelectedCategoryIds((prev) => prev.filter((id) => id !== p.category_id));
                      setCustomTextPrompts((prev) => prev.filter((t) => t !== p.display_name));
                    }}
                  >
                    {p.display_name}
                  </Tag>
                ))}
              </Space>
            </div>
          ) : null}
        </div>
      ) : (
        /* 视觉模式：直接在地图上手绘样例框或采纳当前选中框 */
        <div className="review-ai-block">
          <div className="review-ai-visual-prompt-guide">
            <span>💡 <strong>直接在地图上拖拽画框</strong>，即刻捕获为视觉样例</span>
            <Button
              size="small"
              icon={<AimOutlined />}
              disabled={!selectedIds.length}
              onClick={handleAdoptSelectedBox}
              style={{ width: "100%", marginTop: 6 }}
            >
              采纳当前选中的框
            </Button>
          </div>

          <div className="review-ai-row" style={{ marginTop: 4 }}>
            <span className="review-ai-label">归属树种</span>
            <Select
              size="small"
              value={targetSpecies}
              options={categories.map((c) => ({ value: c.id, label: c.display_name }))}
              onChange={setTargetSpecies}
              style={{ flex: 1 }}
            />
          </div>

          {allVisualExemplars.length ? (
            <div className="review-ai-tags-box">
              <Space size={[4, 4]} wrap>
                {allVisualExemplars.map((ex) => (
                  <Tag
                    key={ex.item_id}
                    closable
                    color="purple"
                    onClose={() => {
                      setVisualExemplarIds([]);
                      setDrawnSampleBoxes([]);
                    }}
                  >
                    当前样本框
                  </Tag>
                ))}
              </Space>
            </div>
          ) : null}
        </div>
      )}

      {/* 参数微调与单行滑轨 */}
      <div className="review-ai-sliders">
        <div className="review-ai-row">
          <span className="review-ai-label">写入策略</span>
          <Segmented
            size="small"
            className="apple-capsule-segmented"
            value={mergeMode}
            options={[
              { value: "append", label: "追加" },
              { value: "replace_all", label: "替换" },
            ]}
            onChange={(val) => setMergeMode(val as "append" | "replace_all")}
          />
          <div className="review-ai-switch-row" style={{ marginLeft: "auto" }}>
            <span style={{ fontSize: 12, color: "var(--review-muted)" }}>自动触发</span>
            <Switch size="small" checked={autoTrigger} onChange={setAutoTrigger} />
          </div>
        </div>

        {/* 置信度：文字 [置信度] ===[滑杆]=== [0.05] 同一行 */}
        <div className="review-ai-inline-slider">
          <span className="review-ai-label">置信度</span>
          <Slider
            min={0.01}
            max={0.95}
            step={0.01}
            value={threshold}
            tooltip={{ formatter: (v) => `${Number(v).toFixed(2)}` }}
            onChange={(v) => setThreshold(Number(v))}
            className="review-inline-slider-control"
          />
          <span className="review-ai-val-text">{threshold.toFixed(2)}</span>
        </div>

        {/* 范围：文字 [范围👁️] ===[滑杆]=== [14.7m/全图] 同一行 */}
        <div className="review-ai-inline-slider">
          <div className="review-ai-label-with-eye">
            <span className="review-ai-label" style={{ width: "auto" }}>范围</span>
            <button
              type="button"
              className="review-ai-eye-mini"
              title={regionMetricsVisible ? "隐藏范围虚线框" : "显示范围虚线框"}
              onClick={() => setRegionMetricsVisible(!regionMetricsVisible)}
            >
              {regionMetricsVisible ? <EyeOutlined /> : <EyeInvisibleOutlined />}
            </button>
          </div>
          <Slider
            min={0}
            max={100}
            step={0.1}
            value={sliderPosition}
            tooltip={{ formatter: (value) => (Number(value) >= 99.8 ? "全图" : `${meterSide.toFixed(1)} m`) }}
            onChange={(value) => setRegionSidePx(value >= 99.8 ? maxSide : sliderToSide(value, maxSide))}
            className="review-inline-slider-control"
          />
          <span className="review-ai-val-text">
            {isFull ? "全图" : `${meterSide.toFixed(1)} m`}
          </span>
        </div>
      </div>

      {/* 当开启了自动触发就隐匿“开始”按钮，未开启时才显示 */}
      {!autoTrigger ? (
        <Button
          type="primary"
          block
          size="middle"
          icon={<ThunderboltOutlined />}
          loading={create.isPending}
          disabled={!hasValidInputs}
          onClick={() => create.mutate()}
          className="review-ai-launch-btn"
        >
          {create.isPending ? "正在启动识别…" : "开始 AI 探测"}
        </Button>
      ) : null}
    </div>
  );
}

function sliderToSide(position: number, maxSide: number) {
  return MIN_REGION_SIDE_PX * Math.pow(maxSide / MIN_REGION_SIDE_PX, position / 100);
}

function sideToSlider(side: number, maxSide: number) {
  if (maxSide <= MIN_REGION_SIDE_PX) return 100;
  return Math.max(0, Math.min(100, (Math.log(side / MIN_REGION_SIDE_PX) / Math.log(maxSide / MIN_REGION_SIDE_PX)) * 100));
}
