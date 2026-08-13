import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { endpoints } from "../api/endpoints";
import {
    getOfflineMode,
    getStoredEndpoint,
    setOfflineMode as saveOfflineMode,
    setStoredEndpoint as saveStoredEndpoint,
} from "../config/env";

export type NodeState = "optimal" | "degraded" | "unreachable" | "offline";

export interface NodeDiagnostics {
    status: string;
    storageStatus?: "ok" | "degraded" | "error";
    databaseStatus?: "ok" | "degraded" | "error";
    activeEndpoint?: string;
    activeBackendPort: string | number;
}

export function useConnectionStatus() {
    const [endpointUrl, setEndpointUrl] = useState<string>(() => getStoredEndpoint());
    const [isOffline, setIsOffline] = useState<boolean>(() => getOfflineMode());
    const [nodeState, setNodeState] = useState<NodeState>("optimal");
    const [rttMs, setRttMs] = useState<number | null>(null);
    const [backendPort, setBackendPort] = useState<string | number | null>(null);
    const [diagnostics, setDiagnostics] = useState<NodeDiagnostics | null>(null);
    const [lastHeartbeat, setLastHeartbeat] = useState<Date | null>(null);
    const [isTesting, setIsTesting] = useState<boolean>(false);

    // 解析当前连接后端端口号：优先读取后端健康探针权威返回，其次尝试从自定义 Endpoint 正则匹配
    const activeBackendPort = useMemo(() => {
        if (backendPort) return String(backendPort);
        if (endpointUrl) {
            const match = endpointUrl.match(/:(\d+)/);
            if (match) return match[1];
        }
        return "";
    }, [backendPort, endpointUrl]);

    const failCountRef = useRef(0);

    const handleUnreachable = useCallback(() => {
        failCountRef.current += 1;
        setRttMs(null);
        setLastHeartbeat(new Date());
        if (failCountRef.current >= 2) {
            setNodeState("unreachable");
        }
    }, []);

    const probe = useCallback(async () => {
        if (isOffline) {
            setNodeState("offline");
            setRttMs(null);
            return;
        }

        const t0 = performance.now();
        try {
            const healthz = await endpoints.checkHealth();
            const latency = Math.round(performance.now() - t0);
            setRttMs(latency);
            setLastHeartbeat(new Date());

            if (healthz && healthz.status === "ok") {
                failCountRef.current = 0;
                if (healthz.port) {
                    setBackendPort(healthz.port);
                }
                try {
                    const readiness = await endpoints.checkReadiness();
                    const storageVal = readiness?.checks?.storage;
                    const dbVal = readiness?.checks?.database;

                    const storageOk = storageVal === "ok";
                    const dbOk = dbVal === "ok";
                    const isDegraded = readiness?.status === "degraded" || (!storageOk || !dbOk);

                    setNodeState(isDegraded ? "degraded" : "optimal");
                    setDiagnostics({
                        status: readiness?.status ?? "ok",
                        storageStatus: storageOk ? "ok" : "degraded",
                        databaseStatus: dbOk ? "ok" : "degraded",
                        activeBackendPort: healthz.port || activeBackendPort,
                    });
                } catch {
                    setNodeState("optimal");
                }
            } else {
                handleUnreachable();
            }
        } catch {
            handleUnreachable();
        }
    }, [isOffline, handleUnreachable, activeBackendPort]);

    /**
     * 通用先验探查：零端口假定，由后端返回权威 port 确认连通
     */
    const testAndApplyEndpoint = async (inputUrl: string): Promise<{ ok: boolean; error?: string }> => {
        const trimmed = inputUrl.trim();
        setIsTesting(true);

        if (!trimmed) {
            saveStoredEndpoint(null);
            setEndpointUrl("");
            setBackendPort(null);
            setIsOffline(false);
            saveOfflineMode(false);
            failCountRef.current = 0;
            setIsTesting(false);
            setTimeout(() => probe(), 50);
            return { ok: true };
        }

        let target = trimmed;
        if (!/^https?:\/\//i.test(target)) {
            target = `http://${target}`;
        }
        const cleanTarget = target.replace(/\/+$/, "");

        const tryFetch = async (url: string) => {
            try {
                const res = await fetch(url, { method: "GET", mode: "cors", signal: AbortSignal.timeout(4000) as any });
                if (res.ok) {
                    const data = await res.json();
                    if (data && data.status === "ok") return { ok: true, data };
                }
            } catch {
                /* ignore */
            }
            return { ok: false };
        };

        const t0 = performance.now();
        let result = await tryFetch(`${cleanTarget}/api/v1/healthz`);
        if (!result.ok) {
            result = await tryFetch(`${cleanTarget}/healthz`);
        }

        if (result.ok && result.data) {
            saveStoredEndpoint(cleanTarget);
            setEndpointUrl(cleanTarget);
            if (result.data.port) {
                setBackendPort(result.data.port);
            }
            setIsOffline(false);
            saveOfflineMode(false);
            failCountRef.current = 0;
            setRttMs(Math.round(performance.now() - t0));
            setNodeState("optimal");
            setIsTesting(false);
            setTimeout(() => probe(), 50);
            return { ok: true };
        }

        setIsTesting(false);
        return { ok: false, error: `无法连通目标服务 (${cleanTarget})，请检查后端 PID 与监听端口` };
    };

    const resetToDefault = () => {
        saveStoredEndpoint(null);
        setEndpointUrl("");
        setBackendPort(null);
        setIsOffline(false);
        saveOfflineMode(false);
        failCountRef.current = 0;
        setTimeout(() => probe(), 50);
    };

    const setOffline = (offline: boolean) => {
        setIsOffline(offline);
        saveOfflineMode(offline);
        if (offline) {
            setNodeState("offline");
            setRttMs(null);
        } else {
            failCountRef.current = 0;
            setTimeout(() => probe(), 50);
        }
    };

    useEffect(() => {
        probe();
        const interval = nodeState === "unreachable" ? 6000 : 30000;
        const timer = setInterval(() => {
            if (!isOffline) probe();
        }, interval);
        return () => clearInterval(timer);
    }, [probe, nodeState, isOffline]);

    return {
        nodeState,
        endpointUrl,
        activeBackendPort,
        rttMs,
        isOffline,
        isTesting,
        diagnostics,
        lastHeartbeat,
        probeNow: probe,
        testAndApplyEndpoint,
        resetToDefault,
        setOffline,
    };
}
