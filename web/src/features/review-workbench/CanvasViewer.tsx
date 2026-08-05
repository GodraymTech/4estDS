import { useRef, useEffect, useState, useCallback } from "react";
import type { CSSProperties, MouseEvent, WheelEvent } from "react";
import type { ReviewCategory, ReviewItem } from "../../entities/review";
import { useReviewWorkbenchStore } from "./store";

interface CanvasViewerProps {
  previewUrl: string;
  items: ReviewItem[];
  categories: ReviewCategory[];
  onSelect: (id: string, additive?: boolean) => void;
  onAddBox?: (boxPx: number[]) => void;
  onUpdateBox?: (id: string, boxPx: number[]) => void;
}

export function CanvasViewer({
  previewUrl,
  items,
  categories,
  onSelect,
  onAddBox,
  onUpdateBox,
}: CanvasViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);

  const zoom = useReviewWorkbenchStore((s) => s.zoom);
  const setZoom = useReviewWorkbenchStore((s) => s.setZoom);
  const pan = useReviewWorkbenchStore((s) => s.pan);
  const setPan = useReviewWorkbenchStore((s) => s.setPan);
  const activeTool = useReviewWorkbenchStore((s) => s.activeTool);
  const selectedIds = useReviewWorkbenchStore((s) => s.selectedIds);
  const activeId = useReviewWorkbenchStore((s) => s.activeId);

  const [imgSize, setImgSize] = useState<{ width: number; height: number }>({ width: 0, height: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [startPan, setStartPan] = useState<{ x: number; y: number }>({ x: 0, y: 0 });

  // 绘制新框时的坐标记录
  const [drawing, setDrawing] = useState<{ x1: number; y1: number; x2: number; y2: number } | null>(null);

  // 控制手柄拖拽
  const [resizing, setResizing] = useState<{ id: string; handle: string; startBox: number[]; startMouse: { x: number; y: number } } | null>(null);

  const categoryColorMap = useMemoMap(categories);

  // 适应容器大小居中
  const fitToScreen = useCallback(() => {
    if (!containerRef.current || !imgSize.width || !imgSize.height) return;
    const { clientWidth, clientHeight } = containerRef.current;
    const scaleX = (clientWidth - 40) / imgSize.width;
    const scaleY = (clientHeight - 40) / imgSize.height;
    const newZoom = Math.min(scaleX, scaleY, 1);
    setZoom(newZoom);
    setPan({
      x: (clientWidth - imgSize.width * newZoom) / 2,
      y: (clientHeight - imgSize.height * newZoom) / 2,
    });
  }, [imgSize, setPan, setZoom]);

  const handleImageLoad = (e: React.SyntheticEvent<HTMLImageElement>) => {
    const img = e.currentTarget;
    setImgSize({ width: img.naturalWidth, height: img.naturalHeight });
  };

  useEffect(() => {
    if (imgSize.width > 0) {
      fitToScreen();
    }
  }, [imgSize.width, fitToScreen]);

  // 鼠标滚轮缩放
  const handleWheel = (e: WheelEvent<HTMLDivElement>) => {
    e.preventDefault();
    const zoomFactor = e.deltaY < 0 ? 1.15 : 0.85;
    const container = containerRef.current;
    if (!container) return;

    const rect = container.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    setZoom((prevZoom) => {
      const nextZoom = Math.max(0.1, Math.min(15, prevZoom * zoomFactor));
      // 保持以光标点为缩放中心
      setPan((prevPan) => ({
        x: mouseX - (mouseX - prevPan.x) * (nextZoom / prevZoom),
        y: mouseY - (mouseY - prevPan.y) * (nextZoom / prevZoom),
      }));
      return nextZoom;
    });
  };

  // 鼠标拖拽平移与创建
  const handleMouseDown = (e: MouseEvent<HTMLDivElement>) => {
    // 按住中键或者在 select 模式下点击空白处平移
    if (e.button === 1 || (activeTool === "select" && e.target === containerRef.current)) {
      setIsPanning(true);
      setStartPan({ x: e.clientX - pan.x, y: e.clientY - pan.y });
      return;
    }

    if (activeTool === "draw" && containerRef.current) {
      const rect = containerRef.current.getBoundingClientRect();
      const canvasX = (e.clientX - rect.left - pan.x) / zoom;
      const canvasY = (e.clientY - rect.top - pan.y) / zoom;
      setDrawing({ x1: canvasX, y1: canvasY, x2: canvasX, y2: canvasY });
    }
  };

  const handleMouseMove = (e: MouseEvent<HTMLDivElement>) => {
    if (isPanning) {
      setPan({ x: e.clientX - startPan.x, y: e.clientY - startPan.y });
      return;
    }

    if (drawing && containerRef.current) {
      const rect = containerRef.current.getBoundingClientRect();
      const canvasX = (e.clientX - rect.left - pan.x) / zoom;
      const canvasY = (e.clientY - rect.top - pan.y) / zoom;
      setDrawing((prev) => (prev ? { ...prev, x2: canvasX, y2: canvasY } : null));
      return;
    }

    if (resizing) {
      const dx = (e.clientX - resizing.startMouse.x) / zoom;
      const dy = (e.clientY - resizing.startMouse.y) / zoom;
      const [x1, y1, x2, y2] = resizing.startBox;
      let nx1 = x1, ny1 = y1, nx2 = x2, ny2 = y2;

      if (resizing.handle.includes("w")) nx1 = Math.min(x2 - 5, x1 + dx);
      if (resizing.handle.includes("e")) nx2 = Math.max(x1 + 5, x2 + dx);
      if (resizing.handle.includes("n")) ny1 = Math.min(y2 - 5, y1 + dy);
      if (resizing.handle.includes("s")) ny2 = Math.max(y1 + 5, y2 + dy);

      onUpdateBox?.(resizing.id, [nx1, ny1, nx2, ny2]);
    }
  };

  const handleMouseUp = () => {
    if (isPanning) setIsPanning(false);

    if (drawing) {
      const x1 = Math.min(drawing.x1, drawing.x2);
      const y1 = Math.min(drawing.y1, drawing.y2);
      const x2 = Math.max(drawing.x1, drawing.x2);
      const y2 = Math.max(drawing.y1, drawing.y2);
      if (x2 - x1 > 4 && y2 - y1 > 4) {
        onAddBox?.([x1, y1, x2, y2]);
      }
      setDrawing(null);
    }

    if (resizing) setResizing(null);
  };

  return (
    <div
      ref={containerRef}
      style={{
        ...CANVAS_CONTAINER,
        cursor: isPanning ? "grabbing" : activeTool === "draw" ? "crosshair" : "default",
      }}
      onWheel={handleWheel}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
    >
      <div
        style={{
          position: "absolute",
          transform: `translate3d(${pan.x}px, ${pan.y}px, 0) scale(${zoom})`,
          transformOrigin: "0 0",
          userSelect: "none",
        }}
      >
        {/* TIFF 底图 */}
        <img
          ref={imgRef}
          src={previewUrl}
          alt="TIFF Preview"
          onLoad={handleImageLoad}
          style={{ display: "block", pointerEvents: "none" }}
          draggable={false}
        />

        {/* BBox 叠加渲染层 */}
        <svg
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: imgSize.width,
            height: imgSize.height,
            overflow: "visible",
          }}
        >
          {items.map((item) => {
            const [x1, y1, x2, y2] = item.box_px ?? [0, 0, 0, 0];
            const width = Math.max(0, x2 - x1);
            const height = Math.max(0, y2 - y1);
            const isSelected = selectedIds.includes(item.id);
            const isActive = activeId === item.id;
            const strokeColor = categoryColorMap.get(item.species) || "#52c99a";

            return (
              <g key={item.id}>
                {/* 检测框本体 */}
                <rect
                  x={x1}
                  y={y1}
                  width={width}
                  height={height}
                  fill={isSelected ? `${strokeColor}22` : "transparent"}
                  stroke={strokeColor}
                  strokeWidth={(isSelected ? 3 : 1.5) / zoom}
                  strokeDasharray={item.status === "pending" ? `${4 / zoom},${4 / zoom}` : undefined}
                  onClick={(e) => {
                    e.stopPropagation();
                    onSelect(item.id, e.ctrlKey || e.metaKey);
                  }}
                  style={{ cursor: "pointer" }}
                />

                {/* 标签文本 */}
                {isSelected && (
                  <text
                    x={x1}
                    y={Math.max(12 / zoom, y1 - 4 / zoom)}
                    fill="#ffffff"
                    fontSize={12 / zoom}
                    fontWeight="bold"
                    style={{ pointerEvents: "none" }}
                  >
                    {item.species || "未设置"} ({item.confidence ? (item.confidence * 100).toFixed(0) : "100"}%)
                  </text>
                )}

                {/* 选中时的 8 方向手柄 */}
                {isActive && (
                  <Handles
                    x1={x1}
                    y1={y1}
                    x2={x2}
                    y2={y2}
                    zoom={zoom}
                    onStartResize={(handle, e) => {
                      e.stopPropagation();
                      setResizing({
                        id: item.id,
                        handle,
                        startBox: [x1, y1, x2, y2],
                        startMouse: { x: e.clientX, y: e.clientY },
                      });
                    }}
                  />
                )}
              </g>
            );
          })}

          {/* 新画框实时预览 */}
          {drawing && (
            <rect
              x={Math.min(drawing.x1, drawing.x2)}
              y={Math.min(drawing.y1, drawing.y2)}
              width={Math.abs(drawing.x2 - drawing.x1)}
              height={Math.abs(drawing.y2 - drawing.y1)}
              fill="rgba(14, 110, 99, 0.15)"
              stroke="#0e6e63"
              strokeWidth={2 / zoom}
              strokeDasharray={`${4 / zoom},${4 / zoom}`}
            />
          )}
        </svg>
      </div>
    </div>
  );
}

function Handles({
  x1,
  y1,
  x2,
  y2,
  zoom,
  onStartResize,
}: {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  zoom: number;
  onStartResize: (handle: string, e: MouseEvent) => void;
}) {
  const size = 8 / zoom;
  const half = size / 2;
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;

  const points = [
    { handle: "nw", x: x1, y: y1 },
    { handle: "n", x: mx, y: y1 },
    { handle: "ne", x: x2, y: y1 },
    { handle: "e", x: x2, y: my },
    { handle: "se", x: x2, y: y2 },
    { handle: "s", x: mx, y: y2 },
    { handle: "sw", x: x1, y: y2 },
    { handle: "w", x: x1, y: my },
  ];

  return (
    <>
      {points.map((p) => (
        <rect
          key={p.handle}
          x={p.x - half}
          y={p.y - half}
          width={size}
          height={size}
          fill="#ffffff"
          stroke="#0e6e63"
          strokeWidth={1.5 / zoom}
          style={{ cursor: `${p.handle}-resize` }}
          onMouseDown={(e) => onStartResize(p.handle, e)}
        />
      ))}
    </>
  );
}

function useMemoMap(categories: ReviewCategory[]) {
  const map = new Map<string, string>();
  for (const c of categories) {
    map.set(c.id, c.color);
    map.set(c.display_name, c.color);
  }
  return map;
}

const CANVAS_CONTAINER: CSSProperties = {
  width: "100%",
  height: "100%",
  overflow: "hidden",
  position: "relative",
  backgroundColor: "var(--bg-canvas, #07110f)",
};
