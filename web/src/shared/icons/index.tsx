/**
 * 复核工作台自定义图标库。
 *
 * 统一规格: viewBox 0 0 24 24、1.5 线宽、currentColor 着色、无填充,
 * 与 antd 线性图标视觉重量保持一致, 可直接放入 Button 的 icon 插槽。
 * 默认边长 1em(跟随父级字号), 颜色继承 color, 天然适配明暗主题切换。
 */
import type { ReactNode, SVGProps } from "react";

export interface IconProps extends Omit<SVGProps<SVGSVGElement>, "children"> {
  /** 图标边长, 默认 1em。 */
  size?: number | string;
}

const BASE = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  focusable: "false",
  "aria-hidden": true,
} as const;

/** 以统一规格包装矢量形状, 生成具名图标组件(避免每个图标重复样板)。 */
function createIcon(displayName: string, shape: ReactNode) {
  function Icon({ size = "1em", ...rest }: IconProps) {
    return (
      <svg {...BASE} width={size} height={size} {...rest}>
        {shape}
      </svg>
    );
  }
  Icon.displayName = displayName;
  return Icon;
}

/** 选择工具(V): 经典箭头指针。 */
export const CursorIcon = createIcon(
  "CursorIcon",
  <path d="M5.5 2.8v16.4l4.2-4.1 2.7 5.7 2.6-1.2-2.7-5.6 5.7-.4z" />,
);

/** 平移工具(H): 手掌抓手。 */
export const HandIcon = createIcon(
  "HandIcon",
  <>
    <path d="M7.6 12.6V6.3a1.35 1.35 0 0 1 2.7 0v4.5" />
    <path d="M10.3 10.8V4.9a1.35 1.35 0 0 1 2.7 0v5.7" />
    <path d="M13 10.6V6.2a1.35 1.35 0 0 1 2.7 0v4.6" />
    <path d="M15.7 11.3V8.7a1.35 1.35 0 0 1 2.7 0v6.1c0 3.4-2.5 6.2-6 6.2h-1.2c-2 0-3.4-.9-4.4-2.5l-2.3-4a1.4 1.4 0 0 1 2.3-1.6l1.8 2.3" />
  </>,
);

/** 画框工具(R): 虚线矩形 + 右下缩放手柄。 */
export const FrameIcon = createIcon(
  "FrameIcon",
  <>
    <rect x="3.3" y="3.3" width="14" height="14" rx="1.6" strokeDasharray="3 2.5" />
    <rect x="15.9" y="15.9" width="4.8" height="4.8" rx="1.2" />
  </>,
);

/** AI 文本提示(T): 星火。 */
export const SparkleIcon = createIcon(
  "SparkleIcon",
  <>
    <path d="M11.1 3.1c.9 4.1 1.8 5 5.9 5.9-4.1.9-5 1.8-5.9 5.9-.9-4.1-1.8-5-5.9-5.9 4.1-.9 5-1.8 5.9-5.9Z" />
    <path d="M17.9 14.6c.45 2.05.9 2.5 2.95 2.95-2.05.45-2.5.9-2.95 2.95-.45-2.05-.9-2.5-2.95-2.95 2.05-.45 2.5-.9 2.95-2.95Z" />
  </>,
);

/** AI 视觉提示(I): 取景框 + 星火。 */
export const SparkleFrameIcon = createIcon(
  "SparkleFrameIcon",
  <>
    <path d="M3.4 8.6V5.6a2.2 2.2 0 0 1 2.2-2.2h3" />
    <path d="M15.4 3.4h3a2.2 2.2 0 0 1 2.2 2.2v3" />
    <path d="M20.6 15.4v3a2.2 2.2 0 0 1-2.2 2.2h-3" />
    <path d="M8.6 20.6h-3a2.2 2.2 0 0 1-2.2-2.2v-3" />
    <path d="M12 8.1c.63 2.9 1.25 3.52 4.15 4.15-2.9.63-3.52 1.25-4.15 4.15-.63-2.9-1.25-3.52-4.15-4.15 2.9-.63 3.52-1.25 4.15-4.15Z" />
  </>,
);

/** 撤销: 圆弧回退箭头。 */
export const UndoIcon = createIcon(
  "UndoIcon",
  <>
    <path d="M9 6.4 4.4 11 9 15.6" />
    <path d="M4.4 11h9.4a5.6 5.6 0 0 1 0 11.2H9" />
  </>,
);

/** 重做: 撤销的镜像。 */
export const RedoIcon = createIcon(
  "RedoIcon",
  <>
    <path d="M15 6.4 19.6 11 15 15.6" />
    <path d="M19.6 11h-9.4a5.6 5.6 0 0 0 0 11.2H15" />
  </>,
);

/** 删除: 细线垃圾桶。 */
export const TrashIcon = createIcon(
  "TrashIcon",
  <>
    <path d="M4.2 6.5h15.6" />
    <path d="M9.6 6.5V4.9a1.4 1.4 0 0 1 1.4-1.4h2a1.4 1.4 0 0 1 1.4 1.4v1.6" />
    <path d="M6.6 6.5l.85 12.3a2 2 0 0 0 2 1.86h5.1a2 2 0 0 0 2-1.86l.85-12.3" />
    <path d="M10.3 10.4v6.4" />
    <path d="M13.7 10.4v6.4" />
  </>,
);

/** 清空工作集: 文档 + 叉。 */
export const ClearIcon = createIcon(
  "ClearIcon",
  <>
    <path d="M13.4 3.4H6.9a2 2 0 0 0-2 2v13.2a2 2 0 0 0 2 2h4.3" />
    <path d="M13.4 3.4 19 9v2.4" />
    <path d="M13.4 3.4V9H19" />
    <path d="M15.1 15.1l5.5 5.5" />
    <path d="M20.6 15.1l-5.5 5.5" />
  </>,
);

/** 有效区域: 虚线多边形。 */
export const EffectiveAreaIcon = createIcon(
  "EffectiveAreaIcon",
  <path d="M12 3.2 20.6 9.5 17.3 20H6.7L3.4 9.5Z" strokeDasharray="3 2.5" />,
);

/** 适配视口: 四角对准框。 */
export const FitViewIcon = createIcon(
  "FitViewIcon",
  <>
    <path d="M3.4 9V6a2.6 2.6 0 0 1 2.6-2.6h3" />
    <path d="M15 3.4h3A2.6 2.6 0 0 1 20.6 6v3" />
    <path d="M20.6 15v3a2.6 2.6 0 0 1-2.6 2.6h-3" />
    <path d="M9 20.6H6A2.6 2.6 0 0 1 3.4 18v-3" />
    <rect x="8.6" y="8.6" width="6.8" height="6.8" rx="1.2" />
  </>,
);

/** 帮助: 细线问号。 */
export const HelpIcon = createIcon(
  "HelpIcon",
  <>
    <circle cx="12" cy="12" r="8.6" />
    <path d="M9.7 9.4a2.35 2.35 0 1 1 3.2 2.2c-.6.23-.9.8-.9 1.44v.5" />
    <path d="M12 16.5h.01" />
  </>,
);

/** 放大。 */
export const ZoomInIcon = createIcon(
  "ZoomInIcon",
  <>
    <path d="M12 5.6v12.8" />
    <path d="M5.6 12h12.8" />
  </>,
);

/** 缩小。 */
export const ZoomOutIcon = createIcon("ZoomOutIcon", <path d="M5.6 12h12.8" />);

/** 底图切换: 图层堆叠。 */
export const LayersIcon = createIcon(
  "LayersIcon",
  <>
    <path d="M12 3.3 2.9 8 12 12.7 21.1 8Z" />
    <path d="M2.9 12.6 12 17.3l9.1-4.7" />
    <path d="M2.9 17.2 12 21.9l9.1-4.7" />
  </>,
);

/** 罗盘: 正北对准。 */
export const CompassIcon = createIcon(
  "CompassIcon",
  <>
    <circle cx="12" cy="12" r="8.6" />
    <path d="M14.9 9.1 13.4 13.4 9.1 14.9 10.6 10.6Z" />
  </>,
);

/** 类别可见。 */
export const EyeIcon = createIcon(
  "EyeIcon",
  <>
    <path d="M2.6 12S6.1 5.9 12 5.9 21.4 12 21.4 12 17.9 18.1 12 18.1 2.6 12 2.6 12Z" />
    <circle cx="12" cy="12" r="3.1" />
  </>,
);

/** 类别隐藏。 */
export const EyeOffIcon = createIcon(
  "EyeOffIcon",
  <>
    <path d="M10.7 6.1a9.3 9.3 0 0 1 1.3-.1c5.9 0 9.4 6 9.4 6a17.6 17.6 0 0 1-2.7 3.5" />
    <path d="M6.7 7.8A17.3 17.3 0 0 0 2.6 12s3.5 6.1 9.4 6.1a9 9 0 0 0 3.7-.78" />
    <path d="M13.9 13.9a3.1 3.1 0 0 1-4.4-4.4" />
    <path d="M3.2 3.2l17.6 17.6" />
  </>,
);

/** 键入数值: 输入框 + 光标。 */
export const NumberInputIcon = createIcon(
  "NumberInputIcon",
  <>
    <rect x="2.9" y="6.6" width="18.2" height="10.8" rx="2.2" />
    <path d="M8.4 9.9v4.2" />
    <path d="M11.6 12h5.2" />
  </>,
);
