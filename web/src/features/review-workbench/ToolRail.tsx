import type { CSSProperties, ReactNode } from "react";
import { Button, Divider, Popover, Segmented, Space, Switch, Tooltip, Typography } from "antd";
import {
  ClearIcon,
  CompassIcon,
  CursorIcon,
  EffectiveAreaIcon,
  FitViewIcon,
  FrameIcon,
  HandIcon,
  HelpIcon,
  LayersIcon,
  RedoIcon,
  SparkleFrameIcon,
  SparkleIcon,
  TrashIcon,
  UndoIcon,
  ZoomInIcon,
  ZoomOutIcon,
} from "../../shared/icons";
import { BASEMAPS } from "../../shared/map-core";
import { useReviewWorkbenchStore, type WorkbenchTool } from "./store";

interface ToolRailProps {
  canUndo?: boolean;
  canRedo?: boolean;
  basemapId?: string;
  roadOverlay?: boolean;
  onUndo?: () => void;
  onRedo?: () => void;
  onDeleteSelected?: () => void;
  onClearWorkspace?: () => void;
  onFitViewport?: () => void;
  onZoomIn?: () => void;
  onZoomOut?: () => void;
  onResetNorth?: () => void;
  onToggleEffectiveArea?: () => void;
  onBasemapChange?: (basemapId: string) => void;
  onRoadOverlayChange?: (enabled: boolean) => void;
  onOpenHelp?: () => void;
}

interface ToolSpec {
  id: WorkbenchTool;
  icon: ReactNode;
  title: string;
  shortcut: string;
}

const TOOLS: ToolSpec[] = [
  { id: "select", icon: <CursorIcon />, title: "选择与框选", shortcut: "V" },
  { id: "pan", icon: <HandIcon />, title: "平移地图", shortcut: "H" },
  { id: "draw", icon: <FrameIcon />, title: "手动画框", shortcut: "R" },
  { id: "ai_text", icon: <SparkleIcon />, title: "AI 文本提示检测", shortcut: "T" },
  { id: "ai_visual", icon: <SparkleFrameIcon />, title: "AI 视觉样例检测", shortcut: "I" },
];

export function ToolRail({
  canUndo = false,
  canRedo = false,
  basemapId,
  roadOverlay = false,
  onUndo,
  onRedo,
  onDeleteSelected,
  onClearWorkspace,
  onFitViewport,
  onZoomIn,
  onZoomOut,
  onResetNorth,
  onToggleEffectiveArea,
  onBasemapChange,
  onRoadOverlayChange,
  onOpenHelp,
}: ToolRailProps) {
  const activeTool = useReviewWorkbenchStore((s) => s.activeTool);
  const setActiveTool = useReviewWorkbenchStore((s) => s.setActiveTool);
  const selectedIds = useReviewWorkbenchStore((s) => s.selectedIds);
  const hasItems = useReviewWorkbenchStore((s) => s.order.length > 0);

  const basemapPanel = (
    <Space direction="vertical" size={10} style={{ width: 190 }}>
      <div>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>底图</Typography.Text>
        <Segmented
          block
          size="small"
          style={{ marginTop: 6 }}
          value={basemapId ?? BASEMAPS[0]?.id}
          onChange={(value) => onBasemapChange?.(String(value))}
          options={BASEMAPS.map((basemap) => ({ value: basemap.id, label: basemap.label }))}
        />
      </div>
      <div style={ROW_BETWEEN}>
        <Typography.Text style={{ fontSize: 12 }}>路网叠加</Typography.Text>
        <Switch size="small" checked={roadOverlay} onChange={(checked) => onRoadOverlayChange?.(checked)} />
      </div>
    </Space>
  );

  return (
    <div style={CONTAINER}>
      {/* 核心标注工具组 */}
      <Space direction="vertical" size={6} style={STACK}>
        {TOOLS.map((tool) => {
          const isActive = activeTool === tool.id;
          return (
            <Tooltip key={tool.id} title={`${tool.title} (${tool.shortcut})`} placement="right">
              <Button
                type={isActive ? "primary" : "text"}
                icon={tool.icon}
                aria-label={tool.title}
                aria-pressed={isActive}
                onClick={() => setActiveTool(tool.id)}
                style={isActive ? ACTIVE_BTN : ACTION_BTN}
              />
            </Tooltip>
          );
        })}
      </Space>

      <Divider style={DIVIDER} />

      {/* 历史与破坏性操作组 */}
      <Space direction="vertical" size={6} style={STACK}>
        <Tooltip title="撤销 (Ctrl+Z)" placement="right">
          <Button type="text" icon={<UndoIcon />} aria-label="撤销" disabled={!canUndo} onClick={onUndo} style={ACTION_BTN} />
        </Tooltip>
        <Tooltip title="重做 (Ctrl+Y)" placement="right">
          <Button type="text" icon={<RedoIcon />} aria-label="重做" disabled={!canRedo} onClick={onRedo} style={ACTION_BTN} />
        </Tooltip>
        <Tooltip title="删除选中对象 (Delete)" placement="right">
          <Button
            type="text"
            danger
            icon={<TrashIcon />}
            aria-label="删除选中对象"
            disabled={selectedIds.length === 0}
            onClick={onDeleteSelected}
            style={ACTION_BTN}
          />
        </Tooltip>
        <Tooltip title="清空当前工作集" placement="right">
          <Button
            type="text"
            danger
            icon={<ClearIcon />}
            aria-label="清空工作集"
            disabled={!hasItems}
            onClick={onClearWorkspace}
            style={ACTION_BTN}
          />
        </Tooltip>
      </Space>

      {/* 底部地图功能组 */}
      <div style={BOTTOM_GROUP}>
        <Tooltip title="显示/隐藏有效区域" placement="right">
          <Button type="text" icon={<EffectiveAreaIcon />} aria-label="有效区域" onClick={onToggleEffectiveArea} style={ACTION_BTN} />
        </Tooltip>
        <Popover content={basemapPanel} title="图层" trigger="click" placement="rightBottom">
          <Tooltip title="底图与路网" placement="right">
            <Button type="text" icon={<LayersIcon />} aria-label="底图切换" style={ACTION_BTN} />
          </Tooltip>
        </Popover>
        <Tooltip title="放大" placement="right">
          <Button type="text" icon={<ZoomInIcon />} aria-label="放大" onClick={onZoomIn} style={ACTION_BTN} />
        </Tooltip>
        <Tooltip title="缩小" placement="right">
          <Button type="text" icon={<ZoomOutIcon />} aria-label="缩小" onClick={onZoomOut} style={ACTION_BTN} />
        </Tooltip>
        <Tooltip title="适配视口" placement="right">
          <Button type="text" icon={<FitViewIcon />} aria-label="适配视口" onClick={onFitViewport} style={ACTION_BTN} />
        </Tooltip>
        <Tooltip title="正北对准" placement="right">
          <Button type="text" icon={<CompassIcon />} aria-label="正北对准" onClick={onResetNorth} style={ACTION_BTN} />
        </Tooltip>
        <Tooltip title="快捷键与使用帮助" placement="right">
          <Button type="text" icon={<HelpIcon />} aria-label="帮助" onClick={onOpenHelp} style={ACTION_BTN} />
        </Tooltip>
      </div>
    </div>
  );
}

const CONTAINER: CSSProperties = {
  width: 48,
  height: "100%",
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  padding: "12px 0",
  borderRight: "1px solid var(--border-color, rgba(125, 125, 125, 0.2))",
  backgroundColor: "var(--bg-toolrail, rgba(0, 0, 0, 0.15))",
  position: "relative",
  overflowY: "auto",
};

const STACK: CSSProperties = { width: "100%", alignItems: "center" };

const ACTION_BTN: CSSProperties = { width: 40, height: 40, fontSize: 18 };

const ACTIVE_BTN: CSSProperties = {
  ...ACTION_BTN,
  backgroundColor: "#0e6e63",
  borderColor: "#0e6e63",
};

const DIVIDER: CSSProperties = { margin: "12px 0", borderColor: "rgba(125,125,125,0.2)" };

const BOTTOM_GROUP: CSSProperties = {
  marginTop: "auto",
  paddingTop: 12,
  display: "flex",
  flexDirection: "column",
  gap: 6,
  alignItems: "center",
};

const ROW_BETWEEN: CSSProperties = { display: "flex", alignItems: "center", justifyContent: "space-between" };
