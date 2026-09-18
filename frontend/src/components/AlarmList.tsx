import { useState } from "react";
import type { Alarm } from "../types";
import { SEVERITY_RANK } from "../types";

const PREVIEW_COUNT = 6;

interface Props {
  alarms: Alarm[];
  onAcknowledge: (alarm: Alarm) => void;
  onResolve: (alarm: Alarm) => void;
}

export function AlarmList({ alarms, onAcknowledge, onResolve }: Props) {
  const [expanded, setExpanded] = useState(false);
  const sorted = [...alarms].sort(
    (a, b) =>
      SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] ||
      Date.parse(b.created_at) - Date.parse(a.created_at),
  );
  const total = sorted.length;
  const shown = expanded ? sorted : sorted.slice(0, PREVIEW_COUNT);

  if (total === 0) {
    return (
      <section className="panel alarm-section alarm-empty">
        <div className="panel-head">
          <h2 className="panel-title">Active alarms</h2>
          <span className="panel-count">0</span>
        </div>
        <div className="empty">No active alarms — all clear.</div>
      </section>
    );
  }

  return (
    <section className="panel alarm-section">
      <div className="panel-head">
        <h2 className="panel-title">Active alarms</h2>
        <span className="panel-count">{total}</span>
      </div>
      <div className="alarm-list">
        {shown.map((alarm) => (
          <AlarmRow key={alarm.alarm_id} alarm={alarm} onAcknowledge={onAcknowledge} onResolve={onResolve} />
        ))}
      </div>
      {total > PREVIEW_COUNT && (
        <button className="panel-more" onClick={() => setExpanded((v) => !v)}>
          {expanded ? "Show fewer" : `View all ${total} active alarms`}
        </button>
      )}
    </section>
  );
}

function AlarmRow({ alarm, onAcknowledge, onResolve }: {
  alarm: Alarm;
  onAcknowledge: (alarm: Alarm) => void;
  onResolve: (alarm: Alarm) => void;
}) {
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

function formatTs(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleTimeString([], { hour12: false });
}