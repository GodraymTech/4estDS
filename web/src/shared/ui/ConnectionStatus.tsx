import { useState, useEffect } from "react";
import type { CSSProperties } from "react";
import { Badge, Button, Popover, Space, Tag, Input, Switch, Tooltip, Typography, message } from "antd";
import {
  ApiOutlined,
  ReloadOutlined,
  UndoOutlined,
  DisconnectOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  CloseCircleOutlined,
} from "@ant-design/icons";
import { useConnectionStatus } from "../lib/useConnectionStatus";
import { DEFAULT_LOCAL_ENDPOINT } from "../config/env";
import "./ConnectionStatus.css";

const { Text } = Typography;

export function ConnectionStatus() {
  const {
    nodeState,
    endpointUrl,
    rttMs,
    isOffline,
    probeNow,
    applyEndpoint,
    setPreset,
    setOffline,
  } = useConnectionStatus();

  const [inputUrl, setInputUrl] = useState(endpointUrl);

  useEffect(() => {
    setInputUrl(endpointUrl);
  }, [endpointUrl]);

  let statusBadge: "success" | "warning" | "error" | "default" = "success";
  let statusText = "已连接";

  if (nodeState === "optimal") {
    statusBadge = "success";
    statusText = "已连接";
  } else if (nodeState === "degraded") {
    statusBadge = "warning";
    statusText = "服务降级";
  } else if (nodeState === "unreachable") {
    statusBadge = "error";
    statusText = "无法连接";
  } else if (nodeState === "offline") {
    statusBadge = "default";
    statusText = "已手动断开";
  }

  const handleSave = () => {
    const clean = inputUrl.trim();
    if (!clean) {
      setPreset("gateway");
      message.success("已恢复默认地址");
      return;
    }
    applyEndpoint(clean);
    message.success("设置已生效");
  };

  const handleReset = () => {
    setInputUrl("");
    setPreset("gateway");
    message.success("已恢复默认地址");
  };

  const popoverContent = (
    <div className="conn-mini-popover">
      {/* 状态行 */}
      <div className="conn-mini-row">
        <Space size={6}>
          {nodeState === "optimal" && <CheckCircleOutlined style={{ color: "#52c41a" }} />}
          {nodeState === "degraded" && <ExclamationCircleOutlined style={{ color: "#faad14" }} />}
          {nodeState === "unreachable" && <CloseCircleOutlined style={{ color: "#ff4d4f" }} />}
          {nodeState === "offline" && <DisconnectOutlined style={{ color: "#8c8c8c" }} />}
          <Text strong style={{ fontSize: 13 }}>{statusText}</Text>
          {rttMs !== null && (
            <Tag color="green" style={{ margin: 0, fontSize: 10, padding: "0 4px" }}>
              {rttMs}ms
            </Tag>
          )}
        </Space>

        <Space size={4}>
          <Tooltip title={isOffline ? "点击恢复自动连接" : "点击手动断开连接"}>
            <Switch
              size="small"
              checked={!isOffline}
              onChange={(checked) => setOffline(!checked)}
            />
          </Tooltip>
          <Tooltip title="立即检测">
            <Button
              type="text"
              size="small"
              icon={<ReloadOutlined style={{ fontSize: 12 }} />}
              onClick={() => probeNow()}
            />
          </Tooltip>
        </Space>
      </div>

      {/* 服务器地址行 */}
      <div className="conn-mini-input">
        <Space.Compact style={{ width: "100%" }}>
          <Input
            size="small"
            placeholder={DEFAULT_LOCAL_ENDPOINT}
            value={inputUrl}
            onChange={(e) => setInputUrl(e.target.value)}
            onPressEnter={handleSave}
            onBlur={handleSave}
          />
          {endpointUrl && (
            <Tooltip title="恢复默认地址 (127.0.0.1:8000)">
              <Button size="small" icon={<UndoOutlined />} onClick={handleReset} />
            </Tooltip>
          )}
        </Space.Compact>
      </div>

      {/* 仅在连接异常时才显示提示 */}
      {nodeState === "unreachable" && (
        <div className="conn-mini-error">
          无法连接到后端服务，请检查服务器地址或端口。
        </div>
      )}
    </div>
  );

  const buttonTooltip = isOffline
    ? "后端服务: 已手动断开"
    : nodeState === "optimal"
    ? `后端服务: 已连接 (${rttMs ?? 0}ms)`
    : "后端服务: 连接异常";

  return (
    <Popover content={popoverContent} trigger="click" placement="bottomRight">
      <Tooltip title={buttonTooltip} mouseEnterDelay={0.5}>
        <Badge status={statusBadge} dot offset={[-3, 3]}>
          <Button
            type="text"
            style={ACTION_STYLE}
            icon={<ApiOutlined />}
            aria-label="后端服务连接"
          />
        </Badge>
      </Tooltip>
    </Popover>
  );
}

const ACTION_STYLE: CSSProperties = { color: "#edf1ef", fontSize: 18 };
