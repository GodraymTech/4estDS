import { useState, useEffect } from "react";
import type { CSSProperties } from "react";
import { Button, Input, InputNumber, Select, Space, Typography, Tag, Divider } from "antd";
import { EditOutlined, DeleteOutlined, CheckOutlined, CloseOutlined } from "@ant-design/icons";
import type { ReviewCategory, ReviewItem } from "../../entities/review";

const { Text } = Typography;

interface ItemInspectorProps {
  item: ReviewItem;
  categories: ReviewCategory[];
  busy: boolean;
  onUpdate: (patch: Record<string, unknown>) => Promise<void>;
  onDelete: () => Promise<void>;
  onEditMask?: () => void;
}

export function ItemInspector({
  item,
  categories,
  busy,
  onUpdate,
  onDelete,
  onEditMask,
}: ItemInspectorProps) {
  const [box, setBox] = useState(item.box_px);
  const [note, setNote] = useState(item.note ?? "");

  useEffect(() => {
    setBox(item.box_px);
    setNote(item.note ?? "");
  }, [item.id, item.box_px?.join(","), item.note]);

  const hasBoxChanged = box?.join(",") !== item.box_px?.join(",");

  return (
    <div style={CONTAINER}>
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        {/* 对象标识与状态 */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <Text strong style={{ fontSize: 14 }}>
            对象 #{item.id.slice(-6)}
          </Text>
          <Tag color={item.status === "accepted" ? "success" : item.status === "rejected" ? "error" : "warning"}>
            {item.status === "accepted" ? "已接受" : item.status === "rejected" ? "已拒绝" : "待确认"}
          </Tag>
        </div>

        {/* 树种类别设置 */}
        <div>
          <Text type="secondary" style={LABEL}>树种类别:</Text>
          <Select
            style={{ width: "100%", marginTop: 4 }}
            value={item.species || undefined}
            placeholder="选择类别"
            options={categories.map((c) => ({ value: c.id, label: c.display_name }))}
            onChange={(species) => onUpdate({ species })}
          />
        </div>

        {/* 状态操作与切换 */}
        <div>
          <Text type="secondary" style={LABEL}>快速判定:</Text>
          <Space size={8} style={{ width: "100%", marginTop: 4 }}>
            <Button
              type={item.status === "accepted" ? "primary" : "default"}
              icon={<CheckOutlined />}
              style={{ flex: 1 }}
              onClick={() => onUpdate({ status: "accepted" })}
            >
              接受
            </Button>
            <Button
              type={item.status === "rejected" ? "primary" : "default"}
              danger={item.status === "rejected"}
              icon={<CloseOutlined />}
              style={{ flex: 1 }}
              onClick={() => onUpdate({ status: "rejected" })}
            >
              拒绝
            </Button>
          </Space>
        </div>

        <Divider style={{ margin: "4px 0" }} />

        {/* 像素框坐标编辑 [x1, y1, x2, y2] */}
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <Text type="secondary" style={LABEL}>像素 BBox 坐标 [x1, y1, x2, y2]:</Text>
            {hasBoxChanged && (
              <Button
                type="link"
                size="small"
                disabled={busy}
                onClick={() => onUpdate({ box_px: box })}
              >
                保存坐标
              </Button>
            )}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginTop: 4 }}>
            {box.map((val, idx) => (
              <InputNumber
                key={idx}
                size="small"
                value={Math.round(val)}
                min={0}
                onChange={(next) =>
                  setBox(box.map((old, at) => (at === idx ? Number(next ?? old) : old)))
                }
              />
            ))}
          </div>
        </div>

        {/* 备注 */}
        <div>
          <Text type="secondary" style={LABEL}>人工备注:</Text>
          <Input.TextArea
            style={{ marginTop: 4 }}
            value={note}
            placeholder="填写备注或修正理由..."
            autoSize={{ minRows: 2, maxRows: 4 }}
            onChange={(e) => setNote(e.target.value)}
            onBlur={() => {
              if (note !== (item.note ?? "")) void onUpdate({ note });
            }}
          />
        </div>

        {/* 实例 Mask & 删除 */}
        <Space direction="vertical" size={6} style={{ width: "100%", marginTop: 4 }}>
          {onEditMask && (
            <Button block icon={<EditOutlined />} onClick={onEditMask}>
              编辑实例 Mask (精细涂抹)
            </Button>
          )}
          <Button block danger icon={<DeleteOutlined />} onClick={onDelete}>
            删除此检测框
          </Button>
        </Space>
      </Space>
    </div>
  );
}

const CONTAINER: CSSProperties = {
  padding: 12,
};

const LABEL: CSSProperties = {
  fontSize: 12,
};
