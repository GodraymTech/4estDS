import {
    useState,
    useRef,
    useEffect,
    useCallback,
    createContext,
    useContext,
    ReactNode,
    CSSProperties,
    MouseEvent as ReactMouseEvent,
} from "react";

export type DockCorner = "top-left" | "bottom-left" | "top-right" | "bottom-right";

interface PanelInfo {
    id: string;
    height: number;
    order: number;
}

interface DockContextType {
    docks: Record<string, DockCorner>;
    setDock: (id: string, corner: DockCorner) => void;
    registerPanel: (id: string, height: number) => void;
    unregisterPanel: (id: string) => void;
    getPlacementStyle: (id: string) => CSSProperties;
    isDraggingAny: boolean;
    setIsDraggingAny: (val: boolean) => void;
}

const DockContext = createContext<DockContextType | null>(null);

let globalOrderCounter = 10;

/** 默认初始停靠优先级（越小越靠近基准角落） */
const INITIAL_PRIORITIES: Record<string, number> = {
    tractTools: 1,
    measure: 2,
    profile: 1,
    tiffTree: 1,
    overview: 1,
    changePanel: 1,
    changeMetrics: 1,
};

/** 默认停靠配置 */
const DEFAULT_INITIAL_DOCKS: Record<string, DockCorner> = {
    tractTools: "bottom-right",
    profile: "bottom-left",
    tiffTree: "bottom-right",
    overview: "bottom-right",
    measure: "top-right",
    changePanel: "top-left",
    changeMetrics: "bottom-left",
};

export function DockProvider({
    children,
    initialDocks = DEFAULT_INITIAL_DOCKS,
}: {
    children: ReactNode;
    initialDocks?: Record<string, DockCorner>;
}) {
    const [docks, setDocks] = useState<Record<string, DockCorner>>(initialDocks);
    const panelsRef = useRef<Map<string, PanelInfo>>(new Map());
    const [, setTick] = useState(0);
    const [isDraggingAny, setIsDraggingAny] = useState(false);

    const setDock = useCallback((id: string, corner: DockCorner) => {
        setDocks((prev) => {
            const p = panelsRef.current.get(id);
            if (p) {
                p.order = ++globalOrderCounter;
            }
            if (prev[id] === corner) {
                setTick((t) => t + 1);
                return prev;
            }
            return { ...prev, [id]: corner };
        });
    }, []);

    const registerPanel = useCallback((id: string, height: number) => {
        const existing = panelsRef.current.get(id);
        if (!existing || Math.abs(existing.height - height) > 2) {
            panelsRef.current.set(id, {
                id,
                height,
                order: existing ? existing.order : (INITIAL_PRIORITIES[id] ?? ++globalOrderCounter),
            });
            setTick((t) => t + 1);
        }
    }, []);

    const unregisterPanel = useCallback((id: string) => {
        if (panelsRef.current.has(id)) {
            panelsRef.current.delete(id);
            setTick((t) => t + 1);
        }
    }, []);

    const getPlacementStyle = useCallback(
        (id: string): CSSProperties => {
            const corner = docks[id] || "bottom-left";
            const side = corner.includes("left") ? "left" : "right";
            const vert = corner.includes("top") ? "top" : "bottom";

            // 筛选出停靠在当前同一个角落的所有 panel，按 order 排序
            const sameCornerPanels: PanelInfo[] = [];
            for (const [pId, pInfo] of panelsRef.current.entries()) {
                if ((docks[pId] || "bottom-left") === corner) {
                    sameCornerPanels.push(pInfo);
                }
            }
            sameCornerPanels.sort((a, b) => a.order - b.order);

            const myIndex = sameCornerPanels.findIndex((p) => p.id === id);

            // 基准边距（顶部留出 64px 避开顶栏，底部留出 16px）
            const baseTop = 64;
            const baseBottom = 16;
            const baseSide = 16;
            const gap = 12;

            if (vert === "top") {
                let currentTop = baseTop;
                for (let i = 0; i < myIndex; i++) {
                    currentTop += sameCornerPanels[i].height + gap;
                }
                return {
                    position: "absolute",
                    [side]: baseSide,
                    top: currentTop,
                    bottom: "auto",
                    zIndex: 8,
                };
            } else {
                let currentBottom = baseBottom;
                for (let i = 0; i < myIndex; i++) {
                    currentBottom += sameCornerPanels[i].height + gap;
                }
                return {
                    position: "absolute",
                    [side]: baseSide,
                    bottom: currentBottom,
                    top: "auto",
                    zIndex: 8,
                };
            }
        },
        [docks],
    );

    return (
        <DockContext.Provider
            value={{
                docks,
                setDock,
                registerPanel,
                unregisterPanel,
                getPlacementStyle,
                isDraggingAny,
                setIsDraggingAny,
            }}
        >
            {children}
        </DockContext.Provider>
    );
}

export function useDockContext() {
    return useContext(DockContext);
}

/**
 * 可拖拽并自动就近角落磁吸防重叠的浮动卡片包装器
 */
export function DraggableDockPanel({
    id,
    children,
    style,
    className,
    dragHandleSelector,
}: {
    id: string;
    children: ReactNode;
    style?: CSSProperties;
    className?: string;
    dragHandleSelector?: string;
}) {
    const ctx = useDockContext();
    const panelRef = useRef<HTMLDivElement>(null);
    const [dragging, setDragging] = useState(false);
    const [dragPos, setDragPos] = useState<{ x: number; y: number } | null>(null);
    const dragStartRef = useRef<{ startX: number; startY: number; initLeft: number; initTop: number }>({
        startX: 0,
        startY: 0,
        initLeft: 0,
        initTop: 0,
    });

    // 测量自身高度并向 DockContext 登记，参与同侧防重叠排版
    useEffect(() => {
        if (!panelRef.current || !ctx) return;
        const el = panelRef.current;
        const updateHeight = () => {
            if (el.offsetHeight > 0) {
                ctx.registerPanel(id, el.offsetHeight);
            }
        };
        updateHeight();
        const ro = new ResizeObserver(updateHeight);
        ro.observe(el);
        return () => {
            ro.disconnect();
            ctx.unregisterPanel(id);
        };
    }, [id, ctx]);

    // 开始拖拽
    const handleMouseDown = (e: ReactMouseEvent<HTMLDivElement>) => {
        // 仅响应鼠标左键 (button === 0)
        if (e.button !== 0) return;

        const target = e.target as HTMLElement;

        // 如果配置了专用抓手选择器，必须点击抓手
        if (dragHandleSelector) {
            if (!target.closest(dragHandleSelector)) return;
        } else {
            // 否则防误触：点击在按钮、输入框、复选框、滚动条、下拉菜单或尺寸调整手柄时不触发拖拽
            if (
                target.closest(
                    "button, input, select, textarea, label, a, .ant-btn, .ant-select, .ant-checkbox-wrapper, .ant-tree, [role='button'], [data-resize-handle='true']"
                )
            ) {
                return;
            }
        }

        if (!panelRef.current) return;
        e.preventDefault();

        const rect = panelRef.current.getBoundingClientRect();
        dragStartRef.current = {
            startX: e.clientX,
            startY: e.clientY,
            initLeft: rect.left,
            initTop: rect.top,
        };

        setDragPos({ x: rect.left, y: rect.top });
        setDragging(true);
        ctx?.setIsDraggingAny(true);

        const onMouseMove = (ev: MouseEvent) => {
            const dx = ev.clientX - dragStartRef.current.startX;
            const dy = ev.clientY - dragStartRef.current.startY;
            setDragPos({
                x: dragStartRef.current.initLeft + dx,
                y: dragStartRef.current.initTop + dy,
            });
        };

        const onMouseUp = (ev: MouseEvent) => {
            window.removeEventListener("mousemove", onMouseMove);
            window.removeEventListener("mouseup", onMouseUp);

            setDragging(false);
            ctx?.setIsDraggingAny(false);

            if (!panelRef.current || !ctx) {
                setDragPos(null);
                return;
            }

            // 计算释放时浮块中心位置
            const currentW = panelRef.current.offsetWidth;
            const currentH = panelRef.current.offsetHeight;
            const finalLeft = dragStartRef.current.initLeft + (ev.clientX - dragStartRef.current.startX);
            const finalTop = dragStartRef.current.initTop + (ev.clientY - dragStartRef.current.startY);

            const centerX = finalLeft + currentW / 2;
            const centerY = finalTop + currentH / 2;

            const winW = window.innerWidth;
            const winH = window.innerHeight;

            // 就近磁吸：左右两边判断
            const isLeft = centerX < winW / 2;
            // 角落优先：上下判断
            const isTop = centerY < winH / 2;

            const targetCorner: DockCorner =
                isTop && isLeft
                    ? "top-left"
                    : !isTop && isLeft
                    ? "bottom-left"
                    : isTop && !isLeft
                    ? "top-right"
                    : "bottom-right";

            ctx.setDock(id, targetCorner);
            setDragPos(null);
        };

        window.addEventListener("mousemove", onMouseMove);
        window.addEventListener("mouseup", onMouseUp);
    };

    const placementStyle = ctx ? ctx.getPlacementStyle(id) : {};

    const computedStyle: CSSProperties = dragging && dragPos
        ? {
              ...style,
              position: "fixed",
              left: dragPos.x,
              top: dragPos.y,
              right: "auto",
              bottom: "auto",
              zIndex: 999,
              transition: "none",
              cursor: "grabbing",
              userSelect: "none",
              boxShadow: "0 12px 36px rgba(0,0,0,0.32)",
          }
        : {
              ...style,
              ...placementStyle,
              transition: "left 0.28s cubic-bezier(0.2, 0, 0, 1), top 0.28s cubic-bezier(0.2, 0, 0, 1), right 0.28s cubic-bezier(0.2, 0, 0, 1), bottom 0.28s cubic-bezier(0.2, 0, 0, 1)",
          };

    return (
        <div
            ref={panelRef}
            style={computedStyle}
            className={className}
            onMouseDown={handleMouseDown}
        >
            {children}
        </div>
    );
}
