import type { Alarm } from "../types";
import { SEVERITY_RANK } from "../types";
import { AlarmRow } from "./AlarmRow";

const PREVIEW_COUNT = 8;

interface Props {
  alarms: Alarm[];
  /** True count of matching (active) alarms, from /stats. */
  total: number;
  onAcknowledge: (alarm: Alarm) => void;
  onResolve: (alarm: Alarm) => void;
  viewAllHref: string;
}

export function AlarmList({ alarms, total, onAcknowledge, onResolve, viewAllHref }: Props) {
  const sorted = [...alarms].sort(
    (a, b) =>
      SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] ||
      Date.parse(b.created_at) - Date.parse(a.created_at),
  );
  const shown = sorted.slice(0, PREVIEW_COUNT);

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
        <span className="panel-count">{total.toLocaleString()}</span>
      </div>
      <div className="alarm-list">
        {shown.map((alarm) => (
          <AlarmRow key={alarm.alarm_id} alarm={alarm} onAcknowledge={onAcknowledge} onResolve={onResolve} />
        ))}
      </div>
      {total > PREVIEW_COUNT && (
        <a className="panel-more" href={viewAllHref}>
          View all {total.toLocaleString()} active alarms
        </a>
      )}
    </section>
  );
}