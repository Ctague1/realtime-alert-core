import type { Alarm, Correlation, Sensor, SensorTimeline, Site, SiteTimeline, Snapshot } from "../types";

// VITE_API_BASE is set at build time for the Docker image
// (e.g. http://localhost:8000). When empty, relative URLs are used so the
// Vite dev-server proxy handles them.
export const API_BASE: string = (import.meta.env.VITE_API_BASE as string) ?? "";

export function wsUrl(): string {
  if (API_BASE) {
    return API_BASE.replace(/^http/, "ws") + "/ws/dashboard";
  }
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws/dashboard`;
}

async function getJson<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`);
  if (!resp.ok) throw new Error(`${path} -> ${resp.status}`);
  return (await resp.json()) as T;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`${path} -> ${resp.status}`);
  return (await resp.json()) as T;
}

export const api = {
  snapshot: () => getJson<Snapshot>("/snapshot"),
  alarms: () => getJson<Alarm[]>("/alarms?status=active&limit=500"),
  sites: () => getJson<Site[]>("/sites"),
  sensors: () => getJson<Sensor[]>("/sensors?limit=2000"),
  acknowledge: (id: number) => postJson<Alarm>(`/alarms/${id}/acknowledge`),
  resolve: (id: number) => postJson<Alarm>(`/alarms/${id}/resolve`),
  reportE2E: (samples: number[]) => postJson<{ accepted: number }>("/metrics/e2e", { samples }),
  siteTimeline: (siteId: string, limit = 100) =>
    getJson<SiteTimeline>(`/sites/${encodeURIComponent(siteId)}/timeline?limit=${limit}`),
  sensorTimeline: (sensorId: string, limit = 100) =>
    getJson<SensorTimeline>(`/sensors/${encodeURIComponent(sensorId)}/timeline?limit=${limit}`),
  correlations: (limit = 50) => getJson<Correlation[]>(`/correlations?limit=${limit}`),
};
