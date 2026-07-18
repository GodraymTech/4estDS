import { useEffect, useMemo, useRef, useState } from "react";
import { Button, Modal, Radio, Slider, Space } from "antd";
import { RedoOutlined, UndoOutlined } from "@ant-design/icons";
import type { ReviewItem, ReviewMaskRle, ReviewMaskStroke } from "../../entities/review";

interface MaskEditorProps {
  open: boolean;
  item: ReviewItem | null;
  saving: boolean;
  onCancel: () => void;
  onSave: (strokes: ReviewMaskStroke[]) => Promise<void>;
}

export function MaskEditor({ open, item, saving, onCancel, onSave }: MaskEditorProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);
  const [mode, setMode] = useState<ReviewMaskStroke["mode"]>("add");
  const [radius, setRadius] = useState(8);
  const [groups, setGroups] = useState<ReviewMaskStroke[][]>([]);
  const [redoGroups, setRedoGroups] = useState<ReviewMaskStroke[][]>([]);
  const baseMask = useMemo(() => item?.mask_rle ? decodeMask(item.mask_rle) : null, [item?.id, item?.mask_rle]);
  const sourceWindow = item?.source_window;

  useEffect(() => {
    if (open) {
      setGroups([]);
      setRedoGroups([]);
      setMode("add");
      setRadius(8);
    }
  }, [open, item?.id]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !baseMask || !sourceWindow) return;
    canvas.width = baseMask.width;
    canvas.height = baseMask.height;
    const preview = new Uint8Array(baseMask.values);
    for (const stroke of groups.flat()) applyStroke(preview, baseMask.width, baseMask.height, sourceWindow, stroke);
    const context = canvas.getContext("2d");
    if (!context) return;
    const image = context.createImageData(baseMask.width, baseMask.height);
    for (let index = 0; index < preview.length; index += 1) {
      const offset = index * 4;
      image.data[offset] = preview[index] ? 82 : 10;
      image.data[offset + 1] = preview[index] ? 201 : 25;
      image.data[offset + 2] = preview[index] ? 154 : 22;
      image.data[offset + 3] = preview[index] ? 220 : 255;
    }
    context.putImageData(image, 0, 0);
  }, [baseMask, groups, sourceWindow]);

  const appendStroke = (event: React.PointerEvent<HTMLCanvasElement>, start: boolean) => {
    if (!baseMask || !sourceWindow) return;
    const canvas = event.currentTarget;
    const bounds = canvas.getBoundingClientRect();
    const localX = (event.clientX - bounds.left) * canvas.width / bounds.width;
    const localY = (event.clientY - bounds.top) * canvas.height / bounds.height;
    const stroke: ReviewMaskStroke = {
      mode,
      x: sourceWindow[0] + localX / canvas.width * sourceWindow[2],
      y: sourceWindow[1] + localY / canvas.height * sourceWindow[3],
      radius,
    };
    setGroups((current) => start
      ? [...current, [stroke]]
      : current.map((group, index) => index === current.length - 1 ? [...group, stroke] : group));
    setRedoGroups([]);
  };

  const strokes = groups.flat();
  return (
    <Modal
      open={open}
      title={`编辑实例 Mask${item?.species ? ` · ${item.species}` : ""}`}
      width={680}
      okText="确认写入草稿"
      cancelText="取消"
      okButtonProps={{ disabled: strokes.length === 0, loading: saving }}
      onCancel={onCancel}
      onOk={() => onSave(strokes)}
      destroyOnClose
    >
      <div className="mask-editor__toolbar">
        <Radio.Group
          optionType="button"
          buttonStyle="solid"
          value={mode}
          options={[{ value: "add", label: "画笔增加" }, { value: "erase", label: "画笔擦除" }]}
          onChange={(event) => setMode(event.target.value as ReviewMaskStroke["mode"])}
        />
        <span>半径 {radius}px</span>
        <Slider min={1} max={64} value={radius} onChange={setRadius} />
        <Space>
          <Button
            icon={<UndoOutlined />}
            disabled={!groups.length}
            onClick={() => {
              setGroups((current) => {
                const last = current[current.length - 1];
                if (last) setRedoGroups((redo) => [...redo, last]);
                return current.slice(0, -1);
              });
            }}
          >局部撤销</Button>
          <Button
            icon={<RedoOutlined />}
            disabled={!redoGroups.length}
            onClick={() => {
              setRedoGroups((current) => {
                const last = current[current.length - 1];
                if (last) setGroups((history) => [...history, last]);
                return current.slice(0, -1);
              });
            }}
          >局部重做</Button>
        </Space>
      </div>
      <canvas
        ref={canvasRef}
        className="mask-editor__canvas"
        aria-label="实例 mask 画笔编辑区"
        onPointerDown={(event) => {
          drawing.current = true;
          event.currentTarget.setPointerCapture(event.pointerId);
          appendStroke(event, true);
        }}
        onPointerMove={(event) => { if (drawing.current) appendStroke(event, false); }}
        onPointerUp={() => { drawing.current = false; }}
        onPointerCancel={() => { drawing.current = false; }}
      />
      <p className="mask-editor__hint">绿色为保留区域。取消不会修改服务端草稿；确认后仍可使用工作台全局撤销。</p>
    </Modal>
  );
}

function decodeMask(mask: ReviewMaskRle): { width: number; height: number; values: Uint8Array } {
  const values = new Uint8Array(mask.width * mask.height);
  let offset = 0;
  let enabled = false;
  for (const count of mask.counts) {
    if (enabled) values.fill(1, offset, offset + count);
    offset += count;
    enabled = !enabled;
  }
  return { width: mask.width, height: mask.height, values };
}

function applyStroke(
  mask: Uint8Array,
  width: number,
  height: number,
  sourceWindow: number[],
  stroke: ReviewMaskStroke,
) {
  const centerX = (stroke.x - sourceWindow[0]) * width / sourceWindow[2];
  const centerY = (stroke.y - sourceWindow[1]) * height / sourceWindow[3];
  const radius = Math.max(0.5, stroke.radius * Math.max(width, height) / Math.max(sourceWindow[2], sourceWindow[3]));
  const minX = Math.max(0, Math.floor(centerX - radius));
  const maxX = Math.min(width - 1, Math.ceil(centerX + radius));
  const minY = Math.max(0, Math.floor(centerY - radius));
  const maxY = Math.min(height - 1, Math.ceil(centerY + radius));
  for (let y = minY; y <= maxY; y += 1) {
    for (let x = minX; x <= maxX; x += 1) {
      if ((x - centerX) ** 2 + (y - centerY) ** 2 <= radius ** 2) {
        mask[y * width + x] = stroke.mode === "add" ? 1 : 0;
      }
    }
  }
}
