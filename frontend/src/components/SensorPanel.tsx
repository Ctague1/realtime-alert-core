import type { Sensor } from "../types";
import { ago } from "../lib/format";

const PREVIEW_COUNT = 8;

interface Props {
  sensors: Sensor[];
  onlineCount: number;
  offlineCount: number;
  viewAllOfflineHref: string;
}

export function SensorPanel({ sensors, onlineCount, offlineCount, viewAllOfflineHref }: Props) {
  const offline = sensors.filter((s) => !s.online);
  const shown = offline.slice(0, PREVIEW_COUNT);

  return (
    <section className="panel sensor-panel">
      <div className="panel-head">
        <h2 className="panel-title">Sensor state</h2>
      </div>
      <div className="panel-stats">
        <span className="sensor-ok">{onlineCount.toLocaleString()} online</span>
        <span className="sensor-off">{offlineCount.toLocaleString()} offline</span>
      </div>
      {offlineCount > 0 && (
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
          {offlineCount > PREVIEW_COUNT && (
            <a className="panel-more" href={viewAllOfflineHref}>
              View all {offlineCount.toLocaleString()} offline sensors
            </a>
          )}
        </>
      )}
      {offlineCount === 0 && <div className="empty">All sensors online.</div>}
    </section>
  );
}