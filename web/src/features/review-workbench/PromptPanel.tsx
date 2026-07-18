import { useMemo, useState } from "react";
import { Alert, Button, Checkbox, Input, InputNumber, Radio, Select, Space, Tag, message } from "antd";
import { ThunderboltOutlined } from "@ant-design/icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { ReviewAttempt, ReviewCategory, ReviewItem } from "../../entities/review";
import { endpoints } from "../../shared/api";

export function PromptPanel({ sessionId, revision, categories, items, onCreated }: {
  sessionId: string;
  revision: number;
  categories: ReviewCategory[];
  items: ReviewItem[];
  onCreated: (attempt: ReviewAttempt) => void;
}) {
  const capabilities = useQuery({ queryKey: ["review-capabilities"], queryFn: endpoints.getReviewCapabilities });
  const [promptType, setPromptType] = useState<"text" | "visual">("text");
  const [selectedCategories, setSelectedCategories] = useState<string[]>(categories.map((item) => item.id));
  const [exemplarIds, setExemplarIds] = useState<string[]>([]);
  const [scope, setScope] = useState<"viewport" | "full">("viewport");
  const [bounds, setBounds] = useState("");
  const [mergeMode, setMergeMode] = useState<"append" | "replace_ai_in_scope">("append");
  const [threshold, setThreshold] = useState(0.25);
  const selected = useMemo(() => categories.filter((item) => selectedCategories.includes(item.id)), [categories, selectedCategories]);
  const exemplars = items.filter((item) => exemplarIds.includes(item.id));

  const create = useMutation({
    mutationFn: () => {
      const parsedBounds = bounds.split(/[\s,]+/).filter(Boolean).map(Number);
      if (scope === "viewport" && (parsedBounds.length !== 4 || parsedBounds.some((value) => !Number.isFinite(value)))) {
        throw new Error("视口范围需要 4 个 WGS84 数值：west,south,east,north");
      }
      return endpoints.createReviewAttempt(sessionId, {
        revision,
        prompt_type: promptType,
        prompts: selected.map((item) => ({ category_id: item.id, display_name: item.display_name, model_prompt: item.model_prompt })),
        visual_exemplars: exemplars.map((item) => ({ item_id: item.id, category_id: item.species, box_px: item.box_px })),
        scope: scope === "full" ? { type: "full" } : { type: "viewport", bounds: parsedBounds },
        merge_mode: mergeMode,
        threshold,
      });
    },
    onSuccess: (attempt) => { onCreated(attempt); message.success("attempt 已进入 review_gpu 队列"); },
    onError: (error) => message.error(error instanceof Error ? error.message : "创建 attempt 失败"),
  });

  return (
    <section>
      <h3>交互式 AI</h3>
      <Space wrap>
        <Tag color={capabilities.data?.available === false ? "error" : "processing"}>{String(capabilities.data?.name ?? "加载能力")}</Tag>
        {capabilities.data?.segmentation ? <Tag>实例分割</Tag> : null}
      </Space>
      {capabilities.data?.available === false ? <Alert type="warning" showIcon message="模型文件不可用" description="请检查 review.models 与 MobileCLIP2 配置。" /> : null}
      <Radio.Group value={promptType} buttonStyle="solid" onChange={(event) => setPromptType(event.target.value)}>
        <Radio.Button value="text">文本 Prompt</Radio.Button>
        <Radio.Button value="visual">视觉样例</Radio.Button>
      </Radio.Group>
      {promptType === "text" ? (
        <Checkbox.Group
          value={selectedCategories}
          options={categories.map((item) => ({ value: item.id, label: `${item.display_name} · ${item.model_prompt}` }))}
          onChange={(value) => setSelectedCategories(value as string[])}
        />
      ) : (
        <Select
          mode="multiple"
          value={exemplarIds}
          placeholder="选择已确认正样本框"
          options={items.filter((item) => item.status === "accepted" && item.species).map((item) => ({ value: item.id, label: `${item.species} · ${item.id}` }))}
          onChange={setExemplarIds}
        />
      )}
      <Radio.Group value={scope} onChange={(event) => setScope(event.target.value)}>
        <Radio value="viewport">当前视口</Radio><Radio value="full">整图</Radio>
      </Radio.Group>
      {scope === "viewport" ? <Input value={bounds} placeholder="WGS84: west,south,east,north" onChange={(event) => setBounds(event.target.value)} /> : null}
      <Select
        value={mergeMode}
        options={[{ value: "append", label: "追加候选" }, { value: "replace_ai_in_scope", label: "替换范围内未确认 AI" }]}
        onChange={setMergeMode}
      />
      <Space><span>置信度</span><InputNumber min={0} max={1} step={0.05} value={threshold} onChange={(value) => setThreshold(Number(value ?? 0.25))} /></Space>
      <Button
        type="primary"
        icon={<ThunderboltOutlined />}
        loading={create.isPending}
        disabled={promptType === "text" ? !selected.length : !exemplars.length}
        onClick={() => create.mutate()}
      >预览配置并执行</Button>
    </section>
  );
}
