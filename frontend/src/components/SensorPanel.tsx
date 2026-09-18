import type { Sensor } from "../types";

export function SensorPanel({ sensors }: { sensors: Sensor[] }) {
  const offline = sensors.filter((s) => !s.online);
  const online = sensors.filter((s) => s.online);

  return (
    <section className="panel">
      <h2>Sensor state</h2>
      <div className="panel-stats">
        <span className="sensor-ok">{online.length} online</span>
        <span className="sensor-off">{offline.length} offline</span>
      </div>
      {offline.length > 0 && (
        <div className="offline-list">
          {offline.slice(0, 30).map((s) => (
            <div key={s.sensor_id} className="offline-row">
              <span>{s.sensor_id}</span>
              <span>{s.site_id}</span>
              <span>last event {ago(s.last_event_ts)}</span>
            </div>
          ))}
        </div>
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