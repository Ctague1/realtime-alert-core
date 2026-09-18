import { useState } from "react";
import type { Correlation } from "../types";

const RULE_LABEL: Record<string, string> = {
  repeat_event: "Repeat event",
  multi_signal_site: "Multi-signal site",
  critical_burst: "Critical burst",
};

const PREVIEW_COUNT = 5;

export function CorrelationPanel({ correlations }: { correlations: Correlation[] }) {
  const [expanded, setExpanded] = useState(false);
  const total = correlations.length;
  const shown = expanded ? correlations : correlations.slice(0, PREVIEW_COUNT);

  return (
    <section className="panel correlation-panel">
      <div className="panel-head">
        <h2 className="panel-title">Correlations & escalations</h2>
        <span className="panel-count">{total}</span>
      </div>
      {total === 0 && <div className="empty">No patterns detected yet.</div>}
      {total > 0 && (
        <div className="correlation-list">
          {shown.map((c) => (
            <div key={c.correlation_id} className={`correlation-row corr-${c.rule}`}>
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
          ))}
        </div>
      )}
      {total > PREVIEW_COUNT && (
        <button className="panel-more" onClick={() => setExpanded((v) => !v)}>
          {expanded ? "Show fewer" : `View all ${total} correlations`}
        </button>
      )}
    </section>
  );
}

function formatTs(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleTimeString([], { hour12: false });
}