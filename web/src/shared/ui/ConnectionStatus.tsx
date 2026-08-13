import { useState, useEffect } from "react";
import type { CSSProperties } from "react";
import { Alert, Badge, Button, Popover, Space, Tag, Input, Switch, Tooltip, Typography, message } from "antd";
import {
    ApiOutlined,
    ReloadOutlined,
    UndoOutlined,
    DisconnectOutlined,
    CheckCircleOutlined,
    ExclamationCircleOutlined,
    CloseCircleOutlined,
    LinkOutlined,
} from "@ant-design/icons";
import { useConnectionStatus } from "../lib/useConnectionStatus";
import "./ConnectionStatus.css";

const { Text } = Typography;

export function ConnectionStatus() {
    const {
        nodeState,
        endpointUrl,
        activeBackendPort,
        rttMs,
        isOffline,
        isTesting,
        probeNow,
        testAndApplyEndpoint,
        resetToDefault,
        setOffline,
    } = useConnectionStatus();

    const [inputUrl, setInputUrl] = useState(endpointUrl);
    const [errorMsg, setErrorMsg] = useState<string | null>(null);

    useEffect(() => {
        setInputUrl(endpointUrl);
        setErrorMsg(null);
    }, [endpointUrl]);

    let statusBadge: "success" | "warning" | "error" | "default" = "success";
    let statusText = `已连接后端 (${activeBackendPort})`;

    if (nodeState === "optimal") {
        statusBadge = "success";
        statusText = `已连接后端 (${activeBackendPort})`;
    } else if (nodeState === "degraded") {
        statusBadge = "warning";
        statusText = `服务降级 (${activeBackendPort})`;
    } else if (nodeState === "unreachable") {
        statusBadge = "error";
        statusText = `端口 ${activeBackendPort} 未响应`;
    } else if (nodeState === "offline") {
        statusBadge = "default";
        statusText = "已手动断开";
    }

    const handleApply = async () => {
        setErrorMsg(null);
        const res = await testAndApplyEndpoint(inputUrl);
        if (res.ok) {
            message.success(inputUrl.trim() ? "已成功连接至新后端节点" : "已恢复默认同源反向代理");
        } else {
            setErrorMsg(res.error || "无法连通目标服务");
        }
    };

    const handleReset = () => {
        setErrorMsg(null);
        setInputUrl("");
        resetToDefault();
        message.success("已恢复默认同源反向代理");
    };

    const popoverContent = (
        <div className="conn-mini-popover" style={{ minWidth: 260 }}>
            {/* 状态行：直接呈现连接到的后端 */}
            <div className="conn-mini-row" style={{ marginBottom: 8 }}>
                <Space size={6}>
                    {nodeState === "optimal" && <CheckCircleOutlined style={{ color: "#52c41a" }} />}
                    {nodeState === "degraded" && <ExclamationCircleOutlined style={{ color: "#faad14" }} />}
                    {nodeState === "unreachable" && <CloseCircleOutlined style={{ color: "#ff4d4f" }} />}
                    {nodeState === "offline" && <DisconnectOutlined style={{ color: "#8c8c8c" }} />}
                    <Text strong style={{ fontSize: 13 }}>{statusText}</Text>
                    {rttMs !== null && !isOffline && (
                        <Tag color="green" style={{ margin: 0, fontSize: 10, padding: "0 4px" }}>
                            {rttMs}ms
                        </Tag>
                    )}
                </Space>

                <Space size={4}>
                    <Tooltip title={isOffline ? "点击连接后端" : "点击断开后端"}>
                        <Switch
                            size="small"
                            checked={!isOffline}
                            onChange={(checked) => setOffline(!checked)}
                        />
                    </Tooltip>
                    <Tooltip title="刷新">
                        <Button
                            type="text"
                            size="small"
                            icon={<ReloadOutlined style={{ fontSize: 12 }} />}
                            onClick={() => probeNow()}
                        />
                    </Tooltip>
                </Space>
            </div>

            {/* 自定义后端端点配置输入框 */}
            <div className="conn-mini-input" style={{ marginBottom: 6 }}>
                <Space.Compact style={{ width: "100%" }}>
                    <Input
                        size="small"
                        addonBefore={<span style={{ fontSize: 12 }}>自定义</span>}
                        placeholder="例: http://localhost:8000"
                        value={inputUrl}
                        disabled={isTesting}
                        onChange={(e) => {
                            setInputUrl(e.target.value);
                            setErrorMsg(null);
                        }}
                        onPressEnter={handleApply}
                    />
                    <Button
                        size="small"
                        type="primary"
                        loading={isTesting}
                        icon={<LinkOutlined />}
                        onClick={handleApply}
                    >
                    </Button>
                    {endpointUrl && (
                        <Tooltip title="恢复默认URL">
                            <Button size="small" icon={<UndoOutlined />} onClick={handleReset} />
                        </Tooltip>
                    )}
                </Space.Compact>
            </div>

            {/* 校验报错反馈 */}
            {errorMsg && (
                <Alert
                    type="error"
                    showIcon
                    style={{ padding: "4px 8px", fontSize: 11, marginTop: 4 }}
                    message={errorMsg}
                />
            )}

            {/* 连不上提示 */}
            {!errorMsg && nodeState === "unreachable" && !isOffline && (
                <div className="conn-mini-error" style={{ marginTop: 4 }}>
                    后端 API 未响应，请检查网络或后端进程状态。
                </div>
            )}
        </div>
    );

    const buttonTooltip = isOffline
        ? "后端: 已断开"
        : nodeState === "optimal"
            ? `后端: 已连接, ${rttMs ?? 0}ms)`
            : `后端: 连接异常`;

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
