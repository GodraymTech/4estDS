import { useState, useRef, useEffect, useCallback, lazy, Suspense } from "react";
import type { CSSProperties, MouseEvent as ReactMouseEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Drawer, Popconfirm, Skeleton, Space, Tag, Typography, message } from "antd";
import {
  CheckCircleFilled,
  CloseCircleFilled,
  FormOutlined,
  LoadingOutlined,
  ReloadOutlined,
  UndoOutlined,
} from "@ant-design/icons";
import { endpoints } from "../../shared/api/endpoints";
import { useAppTheme } from "../../app/providers";

const BlackboardEditor = lazy(() =>
  import("./BlackboardEditor").then((m) => ({ default: m.BlackboardEditor }))
);

const { Text } = Typography;

const DEFAULT_DRAWER_WIDTH = 640;
const MIN_DRAWER_WIDTH = 420;
const STORAGE_KEY = "4estds_blackboard_width";

function clampDrawerWidth(val: number): number {
  const max = typeof window !== "undefined" ? Math.max(MIN_DRAWER_WIDTH, window.innerWidth - 32) : 1600;
  return Math.min(Math.max(val, MIN_DRAWER_WIDTH), max);
}

function getInitialWidth(): number {
  if (typeof window === "undefined") return DEFAULT_DRAWER_WIDTH;
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      const parsed = parseInt(saved, 10);
      if (!Number.isNaN(parsed)) {
        return clampDrawerWidth(parsed);
      }
    }
  } catch {
    // ignore
  }
  return DEFAULT_DRAWER_WIDTH;
}

interface BlackboardDrawerProps {
  open: boolean;
  onClose: () => void;
}

export function BlackboardDrawer({ open, onClose }: BlackboardDrawerProps) {
  const { dark } = useAppTheme();
  const queryClient = useQueryClient();
  const [syncStatus, setSyncStatus] = useState<"idle" | "saving" | "saved" | "error">("saved");
  const [lastSaved, setLastSaved] = useState<string>("");
  const [resetKey, setResetKey] = useState(0);

  const [width, setWidth] = useState<number>(getInitialWidth);
  const [isDragging, setIsDragging] = useState(false);
  const [isHovered, setIsHovered] = useState(false);
  const widthRef = useRef(width);
  widthRef.current = width;

  useEffect(() => {
    const handleWindowResize = () => {
      setWidth((prev) => clampDrawerWidth(prev));
    };
    window.addEventListener("resize", handleWindowResize);
    return () => window.removeEventListener("resize", handleWindowResize);
  }, []);

  useEffect(() => {
    return () => {
      document.body.style.removeProperty("user-select");
      document.body.style.removeProperty("cursor");
    };
  }, []);

  const handleMouseDown = useCallback((e: ReactMouseEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(true);
    const startX = e.clientX;
    const startWidth = widthRef.current;

    const handleMouseMove = (event: MouseEvent) => {
      const deltaX = startX - event.clientX;
      const nextWidth = clampDrawerWidth(startWidth + deltaX);
      widthRef.current = nextWidth;
      setWidth(nextWidth);
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
      document.body.style.removeProperty("user-select");
      document.body.style.removeProperty("cursor");
      try {
        localStorage.setItem(STORAGE_KEY, String(widthRef.current));
      } catch {
        // ignore
      }
    };

    document.body.style.userSelect = "none";
    document.body.style.cursor = "ew-resize";
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
  }, []);

  const handleDoubleClick = useCallback(() => {
    const resetWidth = clampDrawerWidth(DEFAULT_DRAWER_WIDTH);
    widthRef.current = resetWidth;
    setWidth(resetWidth);
    try {
      localStorage.setItem(STORAGE_KEY, String(resetWidth));
    } catch {
      // ignore
    }
  }, []);

  const { data: note, isLoading, isError, refetch } = useQuery({
    queryKey: ["blackboard", "default"],
    queryFn: () => endpoints.getBlackboardNote("default"),
    enabled: open,
    staleTime: 1000 * 15,
  });

  const handleReset = async () => {
    try {
      setSyncStatus("saving");
      await endpoints.resetBlackboardNote("default");
      message.success("公示板已重置");
      await queryClient.invalidateQueries({ queryKey: ["blackboard", "default"] });
      setResetKey((prev) => prev + 1);
      setSyncStatus("saved");
    } catch {
      message.error("重置失败");
      setSyncStatus("error");
    }
  };

  const drawerBg = dark ? "#151d1a" : "#fafcfa";
  const drawerBorder = dark ? "#24322d" : "#e6ece8";

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={width}
      destroyOnClose={false}
      styles={{
        wrapper: isDragging ? { transition: "none" } : undefined,
        content: {
          borderLeft: `1px solid ${drawerBorder}`,
        },
        header: {
          background: drawerBg,
          borderBottom: `1px solid ${drawerBorder}`,
          padding: "14px 20px",
        },
        body: {
          background: drawerBg,
          padding: "16px 20px",
          overflowY: "auto",
        },
        footer: {
          background: drawerBg,
          borderTop: `1px solid ${drawerBorder}`,
          padding: "10px 20px",
        },
      }}
      drawerRender={(node) => (
        <div style={DRAWER_WRAPPER_STYLE}>
          {node}
          <div
            role="separator"
            aria-orientation="vertical"
            aria-valuenow={width}
            title="按住拖拽调整宽度，双击恢复默认"
            style={RESIZE_HANDLE_STYLE}
            onMouseDown={handleMouseDown}
            onDoubleClick={handleDoubleClick}
            onMouseEnter={() => setIsHovered(true)}
            onMouseLeave={() => setIsHovered(false)}
          >
            <div
              style={{
                width: isDragging || isHovered ? 3 : 2,
                height: "100%",
                backgroundColor: isDragging
                  ? "#10b981"
                  : isHovered
                  ? dark
                    ? "#34d399"
                    : "#059669"
                  : dark
                  ? "#334155"
                  : "#cbd5e1",
                boxShadow:
                  isDragging || isHovered
                    ? "0 0 10px rgba(16, 185, 129, 0.6)"
                    : "none",
                transition: isDragging
                  ? "none"
                  : "all 0.15s ease",
                pointerEvents: "none",
              }}
            />
            <div
              style={{
                position: "absolute",
                top: "50%",
                transform: "translateY(-50%)",
                width: isDragging || isHovered ? 6 : 4,
                height: isDragging || isHovered ? 52 : 40,
                borderRadius: 999,
                backgroundColor:
                  isDragging || isHovered
                    ? "#10b981"
                    : dark
                    ? "rgba(255, 255, 255, 0.45)"
                    : "rgba(0, 0, 0, 0.35)",
                boxShadow:
                  isDragging || isHovered
                    ? "0 0 8px rgba(16, 185, 129, 0.8)"
                    : "0 1px 3px rgba(0, 0, 0, 0.15)",
                transition: isDragging ? "none" : "all 0.2s ease",
                pointerEvents: "none",
              }}
            />
          </div>
        </div>
      )}
      title={
        <div style={HEADER_CONTAINER}>
          <div style={TITLE_GROUP}>
            <FormOutlined style={{ color: "#34d399", fontSize: 18 }} />
            <Text strong style={{ fontSize: 16, color: dark ? "#ecfdf5" : "#064e3b" }}>
              公示板
            </Text>
            <Tag color="cyan" style={{ borderRadius: 12, marginInlineStart: 4, fontSize: 11 }}>
              用户共享
            </Tag>
          </div>
          <Space size={12}>
            {syncStatus === "saving" && (
              <Space size={4}>
                <LoadingOutlined style={{ color: "#1890ff", fontSize: 13 }} />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  同步中...
                </Text>
              </Space>
            )}
            {syncStatus === "saved" && (
              <Space size={4}>
                <CheckCircleFilled style={{ color: "#52c41a", fontSize: 13 }} />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  已同步 {lastSaved ? `(${lastSaved})` : ""}
                </Text>
              </Space>
            )}
            {syncStatus === "error" && (
              <Space size={4}>
                <CloseCircleFilled style={{ color: "#ff4d4f", fontSize: 13 }} />
                <Text type="danger" style={{ fontSize: 12 }}>
                  同步失败
                </Text>
              </Space>
            )}

            <Popconfirm
              title="确定要重置公示板吗？"
              description=""
              onConfirm={handleReset}
              okText="确认"
              cancelText="取消"
              okButtonProps={{ danger: true }}
            >
              <Button size="small" type="text" icon={<UndoOutlined />} style={RESET_BTN}>
                重置
              </Button>
            </Popconfirm>
          </Space>
        </div>
      }
    >
      {isLoading && (
        <div style={{ padding: "20px 8px" }}>
          <Skeleton active paragraph={{ rows: 8 }} />
        </div>
      )}

      {isError && (
        <Alert
          type="error"
          message="无法加载公共备忘录"
          description={
            <Space direction="vertical" size={8} style={{ marginTop: 8 }}>
              <span>请检查后端服务连接是否正常。</span>
              <Button size="small" icon={<ReloadOutlined />} onClick={() => refetch()}>
                重试加载
              </Button>
            </Space>
          }
          showIcon
        />
      )}

      {!isLoading && !isError && note && (
        <Suspense
          fallback={
            <div style={{ padding: "20px 8px" }}>
              <Skeleton active paragraph={{ rows: 8 }} />
            </div>
          }
        >
          <BlackboardEditor
            key={`${note.note_id}_${note.updated_at}_${resetKey}`}
            note={note}
            onSyncStatusChange={(status, lastTime) => {
              setSyncStatus(status);
              if (lastTime) setLastSaved(lastTime);
            }}
          />
        </Suspense>
      )}
    </Drawer>
  );
}

const HEADER_CONTAINER: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  width: "100%",
};

const TITLE_GROUP: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
};

const RESET_BTN: CSSProperties = {
  fontSize: 12,
  color: "#94a3b8",
};

const DRAWER_WRAPPER_STYLE: CSSProperties = {
  position: "relative",
  width: "100%",
  height: "100%",
  overflow: "visible",
  pointerEvents: "auto",
};

const RESIZE_HANDLE_STYLE: CSSProperties = {
  position: "absolute",
  left: 0,
  top: 0,
  bottom: 0,
  width: 16,
  transform: "translateX(-50%)",
  cursor: "ew-resize",
  zIndex: 1000,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  userSelect: "none",
  touchAction: "none",
  pointerEvents: "auto",
};


