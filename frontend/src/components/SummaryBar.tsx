import type { Alarm, Sensor } from "../types";
import type { ConnectionStatus } from "../hooks/useDashboard";

interface Props {
  alarms: Alarm[];
  sensors: Sensor[];
  status: ConnectionStatus;
  latency: { totalMs: number; samples: number; e2eAvgMs: number; e2eP95Ms: number };
}

export function SummaryBar({ alarms, sensors, status, latency }: Props) {
  const active = alarms.filter((a) => a.status === "ACTIVE").length;
  const acknowledged = alarms.filter((a) => a.status === "ACKNOWLEDGED").length;
  const critical = alarms.filter((a) => a.severity === "critical").length;
  const offline = sensors.filter((s) => !s.online).length;

  return (
    <header className="summary-bar">
      <div className="summary-title">
        <h1>Project Sentinel</h1>
        <span className={`conn conn-${status}`}>
          {status === "connected" ? "● live" : status === "reconnecting" ? "◌ reconnecting" : "… connecting"}
        </span>
      </div>
      <div className="summary-stats">
        <Stat label="Active" value={active} className="stat-active" />
        <Stat label="Acknowledged" value={acknowledged} className="stat-acked" />
        <Stat label="Critical" value={critical} className="stat-critical" />
        <Stat label="Sensors offline" value={offline} className={offline ? "stat-offline" : ""} />
        <Stat label="Process latency (last)" value={`${Math.round(latency.totalMs)} ms`} />
        <Stat
          label="E2E dashboard (avg/p95)"
          value={`${latency.e2eAvgMs} / ${latency.e2eP95Ms} ms`}
        />
      </div>
    </header>
  );
}

function Stat({ label, value, className }: { label: string; value: number | string; className?: string }) {
  return (
    <div className={`stat ${className ?? ""}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
    </div>
  );
}