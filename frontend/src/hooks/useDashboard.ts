import { useCallback, useEffect, useRef, useState } from "react";
import { api, wsUrl } from "../api/client";
import type { Alarm, DashboardMessage, Sensor, Site } from "../types";

export type ConnectionStatus = "connecting" | "connected" | "reconnecting";

interface DashboardState {
  alarms: Alarm[];
  sites: Site[];
  sensors: Sensor[];
  status: ConnectionStatus;
  connectedSince: number | null;
  latency: { totalMs: number; samples: number; e2eAvgMs: number; e2eP95Ms: number };
}

const MAX_ALARMS = 500;
const E2E_WINDOW = 200;

function emptyState(): DashboardState {
  return {
    alarms: [],
    sites: [],
    sensors: [],
    status: "connecting",
    connectedSince: null,
    latency: { totalMs: 0, samples: 0, e2eAvgMs: 0, e2eP95Ms: 0 },
  };
}

export function useDashboard() {
  const [state, setState] = useState<DashboardState>(emptyState);
  const wsRef = useRef<WebSocket | null>(null);
  const backoffRef = useRef(1);
  const snapshotTimerRef = useRef<number | null>(null);
  const latencyRef = useRef<number[]>([]);
  const e2eRef = useRef<number[]>([]);

  const recordLatency = useCallback((alarm: Alarm) => {
    if (!alarm.source_ts) return;
    const sourceMs = Date.parse(alarm.source_ts);
    if (Number.isNaN(sourceMs)) return;
    const e2e = Date.now() - sourceMs;
    const e2eWindow = e2eRef.current;
    e2eWindow.push(e2e);
    if (e2eWindow.length > E2E_WINDOW) e2eWindow.shift();
  }, []);

  const applyMessage = useCallback((msg: DashboardMessage) => {
    if (msg.kind === "snapshot") {
      setState((prev) => ({
        ...prev,
        alarms: (msg.alarms ?? []).slice(0, MAX_ALARMS),
        sites: msg.sites ?? [],
        sensors: msg.sensors ?? [],
      }));
      return;
    }
    if (msg.kind === "alarm" && msg.alarm) {
      recordLatency(msg.alarm);
      const alarm = msg.alarm;
      setState((prev) => {
        const alarms = new Map(prev.alarms.map((a) => [a.alarm_id, a]));
        if (alarm.status === "RESOLVED") {
          alarms.delete(alarm.alarm_id);
        } else {
          alarms.set(alarm.alarm_id, alarm);
        }
        const arr = [...alarms.values()].slice(0, MAX_ALARMS);
        const sites = new Map(prev.sites.map((s) => [s.site_id, s]));
        if (msg.site) sites.set(msg.site.site_id, msg.site);
        const sensors = new Map(prev.sensors.map((s) => [s.sensor_id, s]));
        if (msg.sensor) sensors.set(msg.sensor.sensor_id, msg.sensor);
        return { ...prev, alarms: arr, sites: [...sites.values()], sensors: [...sensors.values()] };
      });
      return;
    }
    if (msg.kind === "alarms" && msg.updates) {
      setState((prev) => {
        const alarms = new Map(prev.alarms.map((a) => [a.alarm_id, a]));
        const sensors = new Map(prev.sensors.map((s) => [s.sensor_id, s]));
        let totalMs = 0;
        for (const update of msg.updates!) {
          if (!update.alarm) continue;
          recordLatency(update.alarm);
          totalMs = update.latency_ms?.total ?? totalMs;
          if (update.alarm.status === "RESOLVED") {
            alarms.delete(update.alarm.alarm_id);
          } else {
            alarms.set(update.alarm.alarm_id, update.alarm);
          }
          if (update.sensor) sensors.set(update.sensor.sensor_id, update.sensor);
        }
        const e2eWindow = e2eRef.current;
        return {
          ...prev,
          alarms: [...alarms.values()].slice(0, MAX_ALARMS),
          sensors: [...sensors.values()],
          latency: {
            totalMs,
            samples: latencyRef.current.length,
            e2eAvgMs: e2eWindow.length
              ? Math.round(e2eWindow.reduce((a, b) => a + b, 0) / e2eWindow.length)
              : 0,
            e2eP95Ms: e2eWindow.length ? percentile(e2eWindow, 95) : 0,
          },
        };
      });
      return;
    }
    if (msg.kind === "sensor" && msg.sensor) {
      setState((prev) => {
        const sensors = new Map(prev.sensors.map((s) => [s.sensor_id, s]));
        sensors.set(msg.sensor!.sensor_id, msg.sensor!);
        return { ...prev, sensors: [...sensors.values()] };
      });
      return;
    }
    if (msg.kind === "sites" && msg.sites) {
      setState((prev) => ({ ...prev, sites: msg.sites! }));
    }
  }, [recordLatency]);

  const fetchSnapshot = useCallback(async () => {
    try {
      const snap = await api.snapshot();
      applyMessage({ kind: "snapshot", ...snap });
    } catch (err) {
      console.error("snapshot fetch failed", err);
    }
  }, [applyMessage]);

  const connect = useCallback(() => {
    const url = wsUrl();
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      backoffRef.current = 1;
      setState((prev) => ({
        ...prev,
        status: "connected",
        connectedSince: Date.now(),
      }));
      // The server pushes a snapshot on connect; this REST call is a safety
      // net in case that message is missed.
      if (snapshotTimerRef.current) window.clearTimeout(snapshotTimerRef.current);
      snapshotTimerRef.current = window.setTimeout(() => void fetchSnapshot(), 3000);
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data as string) as DashboardMessage;
        applyMessage(msg);
      } catch (err) {
        console.error("bad dashboard message", err);
      }
    };

    ws.onclose = () => {
      setState((prev) => ({ ...prev, status: "reconnecting" }));
      const delay = Math.min(backoffRef.current, 10_000);
      backoffRef.current *= 2;
      window.setTimeout(() => {
        if (wsRef.current === ws) connect();
      }, delay + Math.random() * 250);
    };

    ws.onerror = () => ws.close();
  }, [applyMessage, fetchSnapshot]);

  const pollPeriodic = useCallback(async () => {
    const [sensors, sites] = await Promise.all([api.sensors(), api.sites()]);
    setState((prev) => ({ ...prev, sensors, sites }));
    // Report client-side end-to-end latency samples to the backend so
    // /metrics exposes real e2e numbers (not just the header display).
    const window = e2eRef.current;
    if (window.length) {
      try {
        await api.reportE2E([...window]);
      } catch {
        // Non-fatal; the dashboard keeps working without metrics reporting.
      }
    }
  }, []);

  useEffect(() => {
    connect();
    const pollTimer = window.setInterval(() => void pollPeriodic(), 10_000);
    return () => {
      window.clearInterval(pollTimer);
      if (snapshotTimerRef.current) window.clearTimeout(snapshotTimerRef.current);
      wsRef.current?.close();
    };
  }, [connect, pollPeriodic]);

  const acknowledge = useCallback(async (alarm: Alarm) => {
    try {
      const updated = await api.acknowledge(alarm.alarm_id);
      applyMessage({ kind: "alarm", alarm: updated });
    } catch (err) {
      console.error("acknowledge failed", err);
    }
  }, [applyMessage]);

  const resolve = useCallback(async (alarm: Alarm) => {
    try {
      const updated = await api.resolve(alarm.alarm_id);
      applyMessage({ kind: "alarm", alarm: updated });
    } catch (err) {
      console.error("resolve failed", err);
    }
  }, [applyMessage]);

  return { ...state, acknowledge, resolve };
}

function percentile(values: number[], pct: number): number {
  const sorted = [...values].sort((a, b) => a - b);
  const idx = Math.min(sorted.length - 1, Math.ceil((pct / 100) * sorted.length) - 1);
  return Math.round(sorted[Math.max(idx, 0)]);
}