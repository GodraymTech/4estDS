import { useEffect, useState } from "react";
import { Alert, Button, Divider, Input, InputNumber, Select, Space, Tag, Typography } from "antd";
import { CheckOutlined, CloseOutlined, DeleteOutlined, EditOutlined, LockOutlined } from "@ant-design/icons";
import type { ReviewCategory, ReviewItem } from "../../entities/review";

const { Text } = Typography;

export function ItemInspector({ item, categories, busy, onUpdate, onDelete, onEditMask }: {
  item: ReviewItem;
  categories: ReviewCategory[];
  busy: boolean;
  onUpdate: (patch: Record<string, unknown>) => Promise<void>;
  onDelete: () => Promise<void>;
  onEditMask?: () => void;
}) {
  const [box, setBox] = useState(item.box_px);
  const [note, setNote] = useState(item.note ?? "");
  useEffect(() => { setBox(item.box_px); setNote(item.note ?? ""); }, [item.id, item.box_px.join(","), item.note]);
  const changed = box.join(",") !== item.box_px.join(",");
  return (
    <div className="review-item-inspector">
      <div className="review-item-inspector__heading">
        <Text strong>对象 #{item.id.slice(-6)}</Text>
        <Tag color={item.status === "accepted" ? "success" : item.status === "rejected" ? "error" : "warning"}>{item.status === "accepted" ? "已接受" : item.status === "rejected" ? "已拒绝" : "待确认"}</Tag>
      </div>
      {item.frozen ? <Alert type="info" showIcon icon={<LockOutlined />} message="冻结框" description="追加模式已锁定其几何与树种；仍可修改判定状态和备注。" /> : null}
      <label className="review-field"><Text type="secondary">树种类别</Text><Select disabled={item.frozen} value={item.species || undefined} options={categories.map((category) => ({ value: category.id, label: category.display_name }))} onChange={(species) => void onUpdate({ species })} /></label>
      <div className="review-field"><Text type="secondary">快速判定</Text><Space.Compact block><Button type={item.status === "accepted" ? "primary" : "default"} icon={<CheckOutlined />} onClick={() => void onUpdate({ status: "accepted" })}>接受</Button><Button danger={item.status === "rejected"} type={item.status === "rejected" ? "primary" : "default"} icon={<CloseOutlined />} onClick={() => void onUpdate({ status: "rejected" })}>拒绝</Button></Space.Compact></div>
      <Divider />
      <div className="review-field">
        <div className="review-field__header"><Text type="secondary">像素 BBox [x1, y1, x2, y2]</Text>{changed && !item.frozen ? <Button type="link" size="small" disabled={busy} onClick={() => void onUpdate({ box_px: box })}>保存</Button> : null}</div>
        <div className="review-box-grid">{box.map((value, index) => <InputNumber key={index} size="small" disabled={item.frozen} value={Math.round(value)} min={0} onChange={(next) => setBox(box.map((old, at) => at === index ? Number(next ?? old) : old))} />)}</div>
      </div>
      <label className="review-field"><Text type="secondary">人工备注</Text><Input.TextArea value={note} autoSize={{ minRows: 2, maxRows: 4 }} onChange={(event) => setNote(event.target.value)} onBlur={() => { if (note !== (item.note ?? "")) void onUpdate({ note }); }} /></label>
      {onEditMask && !item.frozen ? <Button block icon={<EditOutlined />} onClick={onEditMask}>编辑实例 Mask</Button> : null}
      <Button block danger icon={<DeleteOutlined />} disabled={item.frozen} onClick={() => void onDelete()}>删除此检测框</Button>
    </div>
  );
}
