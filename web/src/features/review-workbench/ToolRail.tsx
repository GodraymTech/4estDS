import type { CSSProperties } from "react";
import { Button, Tooltip, Divider, Space } from "antd";
import {
  SelectOutlined,
  BorderOutlined,
  RobotOutlined,
  EyeOutlined,
  UndoOutlined,
  RedoOutlined,
  DeleteOutlined,
  QuestionCircleOutlined,
  CompressOutlined,
} from "@ant-design/icons";
import { useReviewWorkbenchStore, type WorkbenchTool } from "./store";

interface ToolRailProps {
  canUndo?: boolean;
  canRedo?: boolean;
  onUndo?: () => void;
  onRedo?: () => void;
  onDeleteSelected?: () => void;
  onFitViewport?: () => void;
  onOpenPrompt?: () => void;
  onOpenHelp?: () => void;
}

export function ToolRail({
  canUndo = false,
  canRedo = false,
  onUndo,
  onRedo,
  onDeleteSelected,
  onFitViewport,
  onOpenPrompt,
  onOpenHelp,
}: ToolRailProps) {
  const activeTool = useReviewWorkbenchStore((s) => s.activeTool);
  const setActiveTool = useReviewWorkbenchStore((s) => s.setActiveTool);
  const selectedIds = useReviewWorkbenchStore((s) => s.selectedIds);

  const tools: Array<{ id: WorkbenchTool; icon: React.ReactNode; title: string; shortcut: string }> = [
    { id: "select", icon: <SelectOutlined />, title: "选择与平移工具", shortcut: "V" },
    { id: "draw", icon: <BorderOutlined />, title: "手动画框框选", shortcut: "R" },
    { id: "ai_text", icon: <RobotOutlined />, title: "AI 文本提示检测", shortcut: "T" },
    { id: "ai_visual", icon: <EyeOutlined />, title: "AI 视觉样例检测", shortcut: "I" },
  ];

  return (
    <div style={CONTAINER}>
      {/* 核心标注工具组 */}
      <Space direction="vertical" size={6} style={{ width: "100%", alignItems: "center" }}>
        {tools.map((t) => {
          const isActive = activeTool === t.id;
          return (
            <Tooltip key={t.id} title={`${t.title} (${t.shortcut})`} placement="right">
              <Button
                type={isActive ? "primary" : "text"}
                icon={t.icon}
                onClick={() => {
                  setActiveTool(t.id);
                  if (t.id === "ai_text" || t.id === "ai_visual") {
                    onOpenPrompt?.();
                  }
                }}
                style={{
                  width: 36,
                  height: 36,
                  backgroundColor: isActive ? "#0e6e63" : undefined,
                  borderColor: isActive ? "#0e6e63" : undefined,
                }}
              />
            </Tooltip>
          );
        })}
      </Space>

      <Divider style={{ margin: "12px 0", borderColor: "rgba(125,125,125,0.2)" }} />

      {/* 快捷操作组 */}
      <Space direction="vertical" size={6} style={{ width: "100%", alignItems: "center" }}>
        <Tooltip title="撤销 (Ctrl+Z)" placement="right">
          <Button
            type="text"
            icon={<UndoOutlined />}
            disabled={!canUndo}
            onClick={onUndo}
            style={ACTION_BTN}
          />
        </Tooltip>
        <Tooltip title="重做 (Ctrl+Y)" placement="right">
          <Button
            type="text"
            icon={<RedoOutlined />}
            disabled={!canRedo}
            onClick={onRedo}
            style={ACTION_BTN}
          />
        </Tooltip>
        <Tooltip title="删除选中对象 (Delete)" placement="right">
          <Button
            type="text"
            danger
            icon={<DeleteOutlined />}
            disabled={selectedIds.length === 0}
            onClick={onDeleteSelected}
            style={ACTION_BTN}
          />
        </Tooltip>
      </Space>

      {/* 底部功能辅助组 */}
      <div style={BOTTOM_GROUP}>
        <Tooltip title="适配视口居中" placement="right">
          <Button
            type="text"
            icon={<CompressOutlined />}
            onClick={onFitViewport}
            style={ACTION_BTN}
          />
        </Tooltip>
        <Tooltip title="快捷键与使用帮助" placement="right">
          <Button
            type="text"
            icon={<QuestionCircleOutlined />}
            onClick={onOpenHelp}
            style={ACTION_BTN}
          />
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
};

const ACTION_BTN: CSSProperties = {
  width: 36,
  height: 36,
};

const BOTTOM_GROUP: CSSProperties = {
  marginTop: "auto",
  display: "flex",
  flexDirection: "column",
  gap: 6,
  alignItems: "center",
};
