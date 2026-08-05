import { useState, useEffect, useCallback, useRef } from "react";
import { endpoints } from "../api/endpoints";
import {
  DEFAULT_LOCAL_ENDPOINT,
  getOfflineMode,
  getStoredEndpoint,
  setOfflineMode as saveOfflineMode,
  setStoredEndpoint as saveStoredEndpoint,
} from "../config/env";

export type NodeState = "optimal" | "degraded" | "unreachable" | "offline";
export type EndpointPreset = "local" | "gateway" | "custom";

export interface NodeDiagnostics {
  status: string;
  storageStatus?: "ok" | "degraded" | "error";
  databaseStatus?: "ok" | "degraded" | "error";
  activeEndpoint: string;
  preset: EndpointPreset;
}

export function useConnectionStatus() {
  const [endpointUrl, setEndpointUrl] = useState<string>(() => getStoredEndpoint());
  const [isOffline, setIsOffline] = useState<boolean>(() => getOfflineMode());
  const [nodeState, setNodeState] = useState<NodeState>("optimal");
  const [rttMs, setRttMs] = useState<number | null>(null);
  const [diagnostics, setDiagnostics] = useState<NodeDiagnostics | null>(null);
  const [lastHeartbeat, setLastHeartbeat] = useState<Date | null>(null);
  const failCountRef = useRef(0);

  const preset: EndpointPreset = !endpointUrl
    ? "gateway"
    : endpointUrl === DEFAULT_LOCAL_ENDPOINT
    ? "local"
    : "custom";

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
            activeEndpoint: getStoredEndpoint() || "localhost:8000 (代理默认)",
            preset,
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
  }, [isOffline, preset]);

  const handleUnreachable = () => {
    failCountRef.current += 1;
    setRttMs(null);
    setLastHeartbeat(new Date());
    if (failCountRef.current >= 2) {
      setNodeState("unreachable");
    }
  };

  const applyEndpoint = (url: string | null) => {
    saveStoredEndpoint(url);
    setEndpointUrl(url || "");
    setIsOffline(false);
    saveOfflineMode(false);
    failCountRef.current = 0;
    setTimeout(() => {
      probe();
    }, 50);
  };

  const setPreset = (targetPreset: EndpointPreset) => {
    if (targetPreset === "gateway") {
      applyEndpoint(null);
    } else if (targetPreset === "local") {
      applyEndpoint(DEFAULT_LOCAL_ENDPOINT);
    }
  };

  const setOffline = (offline: boolean) => {
    setIsOffline(offline);
    saveOfflineMode(offline);
    if (offline) {
      setNodeState("offline");
      setRttMs(null);
    } else {
      failCountRef.current = 0;
      setTimeout(() => {
        probe();
      }, 50);
    }
  };

  const pingTest = async (targetUrl: string): Promise<{ ok: boolean; rtt?: number; error?: string }> => {
    const t0 = performance.now();
    const clean = targetUrl.trim().replace(/\/+$/, "");
    let url = `${clean}/healthz`;
    if (!clean.startsWith("http://") && !clean.startsWith("https://")) {
      url = clean.startsWith("/") ? `${clean}/healthz` : `/${clean}/healthz`;
    }

    try {
      const res = await fetch(url, { method: "GET" });
      const elapsed = Math.round(performance.now() - t0);
      if (res.ok) {
        return { ok: true, rtt: elapsed };
      }
      return { ok: false, error: `HTTP ${res.status} ${res.statusText}` };
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : "节点拒绝连接" };
    }
  };

  useEffect(() => {
    probe();
    const interval = nodeState === "unreachable" ? 5000 : 30000;
    const timer = setInterval(() => {
      if (!isOffline) probe();
    }, interval);
    return () => clearInterval(timer);
  }, [probe, nodeState, isOffline]);

  return {
    nodeState,
    preset,
    endpointUrl,
    rttMs,
    diagnostics,
    lastHeartbeat,
    isOffline,
    probeNow: probe,
    applyEndpoint,
    setPreset,
    setOffline,
    pingTest,
  };
}
