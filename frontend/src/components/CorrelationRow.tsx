import type { Correlation } from "../types";
import { formatTs } from "../lib/format";

const RULE_LABEL: Record<string, string> = {
  repeat_event: "Repeat event",
  multi_signal_site: "Multi-signal site",
  critical_burst: "Critical burst",
};

export function CorrelationRow({ correlation: c }: { correlation: Correlation }) {
  return (
    <div className={`correlation-row corr-${c.rule}`}>
      <div className="corr-main">
        <span className="corr-rule">{RULE_LABEL[c.rule] ?? c.rule}</span>
        <span className="corr-site">{c.site_id}</span>
        {c.sensor_id && <span className="corr-sensor">{c.sensor_id}</span>}
      </div>
      <div className="corr-desc">{c.description}</div>
      <div className="corr-meta">
        <span className={`corr-sev ${c.severity_after === "critical" ? "sev-critical" : ""}`}>
          {c.severity_before} <span className="corr-arrow">→</span> {c.severity_after}
        </span>
        <span className="corr-time">{formatTs(c.detected_at)}</span>
      </div>
    </div>
  );
}