import type { CSSProperties, ReactNode } from "react";
import { Button, Select, Space, Switch, Tooltip, Typography } from "antd";
import { CompassOutlined, HomeOutlined, MinusOutlined, PlusOutlined } from "@ant-design/icons";
import { BASEMAPS } from "../map-core";

const { Text } = Typography;

export function MapFloatingToolbar({
  basemapId,
  onBasemapChange,
  roadVisible,
  onRoadVisibleChange,
  zoomLabel,
  homeTitle = "回到地块视野",
  onZoomIn,
  onZoomOut,
  onHome,
  onResetNorth,
  extraActions,
}: {
  basemapId: string;
  onBasemapChange: (value: string) => void;
  roadVisible: boolean;
  onRoadVisibleChange: (value: boolean) => void;
  zoomLabel?: string;
  homeTitle?: string;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onHome: () => void;
  onResetNorth?: () => void;
  extraActions?: ReactNode;
}) {
  return (
    <>
      <div style={TOP_TOOLBAR}>
        <div style={LAYER_PANEL}>
          <Select
            size="small"
            value={basemapId}
            onChange={onBasemapChange}
            options={BASEMAPS.map((b) => ({ value: b.id, label: b.label }))}
            style={BASEMAP_SELECT}
          />
          <Space size={8}>
            <Text style={PANEL_TEXT}>路网</Text>
            <Switch size="small" checked={roadVisible} onChange={onRoadVisibleChange} />
          </Space>
        </div>
        <div style={RIGHT_TOOLS}>
          <ToolbarButton title="放大" icon={<PlusOutlined />} onClick={onZoomIn} />
          {zoomLabel ? <div style={ZOOM_BADGE}>{zoomLabel}</div> : null}
          <ToolbarButton title="缩小" icon={<MinusOutlined />} onClick={onZoomOut} />
          <ToolbarButton title={homeTitle} icon={<HomeOutlined />} onClick={onHome} />
          {extraActions}
        </div>
      </div>
      {onResetNorth ? (
        <div style={COMPASS_PANEL}>
          <ToolbarButton title="指北" icon={<CompassOutlined />} onClick={onResetNorth} />
        </div>
      ) : null}
    </>
  );
}

function ToolbarButton({
  title,
  icon,
  onClick,
}: {
  title: string;
  icon: ReactNode;
  onClick: () => void;
}) {
  return (
    <Tooltip title={title} placement="bottom">
      <Button type="text" icon={icon} onClick={onClick} style={TOOL_BUTTON} />
    </Tooltip>
  );
}

const GLASS: CSSProperties = {
  background: "var(--glass-bg)",
  border: "1px solid var(--glass-border)",
  boxShadow: "var(--glass-shadow), var(--glass-inner)",
  backdropFilter: "blur(16px) saturate(150%)",
};
const TOP_TOOLBAR: CSSProperties = {
  position: "absolute",
  top: 12,
  right: 64,
  zIndex: 8,
  maxWidth: "calc(100% - 370px)",
  display: "flex",
  alignItems: "center",
  justifyContent: "flex-end",
  gap: 8,
  overflowX: "auto",
  scrollbarWidth: "none",
};
const LAYER_PANEL: CSSProperties = {
  ...GLASS,
  borderRadius: 14,
  padding: "6px 8px",
  display: "flex",
  alignItems: "center",
  gap: 8,
  flex: "0 0 auto",
};
const BASEMAP_SELECT: CSSProperties = { width: 76 };
const PANEL_TEXT: CSSProperties = { fontSize: 12, color: "var(--glass-text)" };
const RIGHT_TOOLS: CSSProperties = {
  ...GLASS,
  height: 42,
  borderRadius: 15,
  padding: 4,
  display: "flex",
  flexDirection: "row",
  alignItems: "center",
  gap: 2,
  flex: "0 0 auto",
};
const TOOL_BUTTON: CSSProperties = {
  width: 34,
  height: 34,
  borderRadius: 11,
  color: "var(--glass-text)",
};
const ZOOM_BADGE: CSSProperties = {
  minWidth: 38,
  textAlign: "center",
  color: "var(--glass-text)",
  fontSize: 12,
  fontWeight: 700,
  fontVariantNumeric: "tabular-nums",
};
const COMPASS_PANEL: CSSProperties = {
  ...GLASS,
  position: "absolute",
  right: 12,
  top: 12,
  zIndex: 8,
  width: 42,
  height: 42,
  borderRadius: 15,
  padding: 3,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
};
