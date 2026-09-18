import type { Alarm } from "../types";
import { formatTs } from "../lib/format";

interface Props {
  alarm: Alarm;
  onAcknowledge: (alarm: Alarm) => void;
  onResolve: (alarm: Alarm) => void;
}

export function AlarmRow({ alarm, onAcknowledge, onResolve }: Props) {
  const isCritical = alarm.severity === "critical";
  return (
    <div className={`alarm-row severity-${alarm.severity} status-${alarm.status.toLowerCase()}`}>
      <div className="alarm-main">
        {isCritical && <span className="critical-label">CRITICAL</span>}
        <span className="alarm-type">{alarm.type}</span>
        <span className="alarm-id">{alarm.event_id}</span>
      </div>
      <div className="alarm-meta">
        <span>site {alarm.site_id}</span>
        <span>sensor {alarm.sensor_id}</span>
        <span>{formatTs(alarm.source_ts ?? alarm.created_at)}</span>
        <span className={`badge badge-${alarm.severity}`}>{alarm.severity}</span>
        <span className={`badge badge-status ${alarm.status.toLowerCase()}`}>{alarm.status}</span>
      </div>
      <div className="alarm-actions">
        {alarm.status === "ACTIVE" && (
          <button onClick={() => onAcknowledge(alarm)}>Acknowledge</button>
        )}
        {alarm.status !== "RESOLVED" && (
          <button onClick={() => onResolve(alarm)}>Resolve</button>
        )}
      </div>
    </div>
  );
}