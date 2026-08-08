import { useEffect, useState } from "react";
import { Alert, Button, Divider, Input, InputNumber, Select, Tag, Typography } from "antd";
import { DeleteOutlined, EditOutlined, LockOutlined } from "@ant-design/icons";
import type { ReviewCategory, ReviewItem } from "../../entities/review";

const { Text } = Typography;

export function ItemInspector({
  item,
  categories,
  busy,
  onUpdate,
  onDelete,
  onEditMask,
}: {
  item: ReviewItem;
  categories: ReviewCategory[];
  busy: boolean;
  onUpdate: (patch: Record<string, unknown>) => Promise<void>;
  onDelete: () => Promise<void>;
  onEditMask?: () => void;
}) {
  const [box, setBox] = useState(item.box_px);
  const [note, setNote] = useState(item.note ?? "");

  useEffect(() => {
    setBox(item.box_px);
    setNote(item.note ?? "");
  }, [item.id, item.box_px.join(","), item.note]);

  const changed = box.join(",") !== item.box_px.join(",");

  return (
    <div className="review-item-inspector">
      <div className="review-item-inspector__heading">
        <Text strong style={{ fontSize: 13 }}>
          对象属性 #{item.id.slice(-6)}
        </Text>
        {item.confidence != null ? (
          <Tag color="cyan" style={{ fontFamily: "monospace", fontVariantNumeric: "tabular-nums" }}>
            置信度: {Number(item.confidence).toFixed(2)}
          </Tag>
        ) : (
          <Tag color="blue">人工标注 (1.00)</Tag>
        )}
      </div>

      {item.frozen ? (
        <Alert
          type="info"
          showIcon
          icon={<LockOutlined />}
          message="冻结框（存量真值）"
          description="追加模式已锁定其几何坐标与树种，仅可编辑备注。"
        />
      ) : null}

      <label className="review-field">
        <Text type="secondary" style={{ fontSize: 12 }}>
          树种类别
        </Text>
        <Select
          disabled={item.frozen}
          value={item.species || undefined}
          options={categories.map((category) => ({ value: category.id, label: category.display_name }))}
          onChange={(species) => void onUpdate({ species })}
        />
      </label>

      <Divider style={{ margin: "6px 0" }} />

      <div className="review-field">
        <div className="review-field__header">
          <Text type="secondary" style={{ fontSize: 12 }}>
            像素坐标 BBox [x1, y1, x2, y2]
          </Text>
          {changed && !item.frozen ? (
            <Button type="link" size="small" disabled={busy} onClick={() => void onUpdate({ box_px: box })}>
              保存修改
            </Button>
          ) : null}
        </div>
        <div className="review-box-grid">
          {box.map((value, index) => (
            <InputNumber
              key={index}
              size="small"
              disabled={item.frozen}
              value={Math.round(value)}
              min={0}
              onChange={(next) =>
                setBox(box.map((old, at) => (at === index ? Number(next ?? old) : old)))
              }
            />
          ))}
        </div>
      </div>

      <label className="review-field">
        <Text type="secondary" style={{ fontSize: 12 }}>
          人工备注
        </Text>
        <Input.TextArea
          value={note}
          placeholder="可在此输入该单木特征或解译说明..."
          autoSize={{ minRows: 2, maxRows: 4 }}
          onChange={(event) => setNote(event.target.value)}
          onBlur={() => {
            if (note !== (item.note ?? "")) void onUpdate({ note });
          }}
        />
      </label>

      {onEditMask && !item.frozen ? (
        <Button block icon={<EditOutlined />} onClick={onEditMask}>
          精细编辑实例 Mask
        </Button>
      ) : null}

      <Button block danger icon={<DeleteOutlined />} disabled={item.frozen} onClick={() => void onDelete()}>
        删除此检测框
      </Button>
    </div>
  );
}
