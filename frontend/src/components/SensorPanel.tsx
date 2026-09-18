import { useState } from "react";
import type { Sensor } from "../types";

const PREVIEW_COUNT = 8;

export function SensorPanel({ sensors }: { sensors: Sensor[] }) {
  const [expanded, setExpanded] = useState(false);
  const offline = sensors.filter((s) => !s.online);
  const online = sensors.filter((s) => s.online);
  const shown = expanded ? offline : offline.slice(0, PREVIEW_COUNT);

  return (
    <section className="panel sensor-panel">
      <div className="panel-head">
        <h2 className="panel-title">Sensor state</h2>
      </div>
      <div className="panel-stats">
        <span className="sensor-ok">{online.length} online</span>
        <span className="sensor-off">{offline.length} offline</span>
      </div>
      {offline.length > 0 && (
        <>
          <div className="offline-list">
            {shown.map((s) => (
              <div key={s.sensor_id} className="offline-row">
                <span>{s.sensor_id}</span>
                <span>{s.site_id}</span>
                <span>last event {ago(s.last_event_ts)}</span>
              </div>
            ))}
          </div>
          {offline.length > PREVIEW_COUNT && (
            <button className="panel-more" onClick={() => setExpanded((v) => !v)}>
              {expanded ? "Show fewer" : `View all ${offline.length} offline sensors`}
            </button>
          )}
        </>
      )}
      {offline.length === 0 && <div className="empty">All sensors online.</div>}
    </section>
  );
}

function ago(ts?: string | null): string {
  if (!ts) return "never";
  const secs = Math.round((Date.now() - Date.parse(ts)) / 1000);
  if (secs < 0) return "now";
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  return `${Math.round(secs / 3600)}h ago`;
}