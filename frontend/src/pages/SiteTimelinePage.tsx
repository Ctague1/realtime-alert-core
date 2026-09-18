import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { CorrelationRow } from "../components/CorrelationRow";
import { PillFilter, type PillOption } from "../components/PillFilter";
import { ago, formatTs } from "../lib/format";
import type { SiteTimeline as SiteTimelineData, TimelineEvent } from "../types";

const RULE_FILTERS: PillOption[] = [
  { value: "all", label: "All" },
  { value: "repeat_event", label: "Repeat event" },
  { value: "multi_signal_site", label: "Multi-signal" },
  { value: "critical_burst", label: "Critical burst" },
];

const SEVERITY_FILTERS: PillOption[] = [
  { value: "all", label: "All" },
  { value: "critical", label: "Critical" },
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
  { value: "informational", label: "Info" },
];

export function SiteTimelinePage({ siteId }: { siteId: string }) {
  const [data, setData] = useState<SiteTimelineData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ruleFilter, setRuleFilter] = useState("all");
  const [severityFilter, setSeverityFilter] = useState("all");
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const timeline = await api.siteTimeline(siteId, 100);
        if (!cancelled) {
          setData(timeline);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(String(err));
      }
    };
    void load();
    timerRef.current = window.setInterval(() => void load(), 10_000);
    return () => {
      cancelled = true;
      if (timerRef.current) window.clearInterval(timerRef.current);
    };
  }, [siteId]);

  const correlations = useMemo(
    () =>
      ruleFilter === "all"
        ? data?.correlations ?? []
        : (data?.correlations ?? []).filter((c) => c.rule === ruleFilter),
    [data, ruleFilter],
  );
  const events = useMemo(
    () =>
      severityFilter === "all"
        ? data?.events ?? []
        : (data?.events ?? []).filter((e) => e.severity === severityFilter),
    [data, severityFilter],
  );

  const site = data?.site;

  return (
    <div className="browse-page timeline-page">
      <header className="browse-head">
        <a className="back-link" href="#/">
          ← Dashboard
        </a>
        <div className="browse-heading">
          <h1 className="browse-title">Site timeline</h1>
          <p className="browse-subtitle">{siteId}</p>
        </div>
        {site && (
          <span className={`badge badge-${site.highest_active_severity ?? "low"}`}>
            {site.highest_active_severity ?? "clear"}
          </span>
        )}
      </header>

      {!data && !error && <div className="browse-status">Loading…</div>}
      {error && (
        <div className="browse-status browse-error">
          Failed to load timeline: {error}
        </div>
      )}

      {data && !error && (
        <div className="timeline-content">
          <section className="panel site-summary">
            <div className="panel-head">
              <h2 className="panel-title">Site summary</h2>
            </div>
            <div className="site-summary-grid">
              <SummaryStat label="Status" value={data.site.status} />
              <SummaryStat
                label="Active alarms"
                value={data.site.active_alarm_count.toLocaleString()}
              />
              <SummaryStat
                label="Highest severity"
                value={data.site.highest_active_severity ?? "clear"}
                severity={data.site.highest_active_severity ?? undefined}
              />
              <SummaryStat label="Latest event" value={ago(data.site.latest_event_ts)} />
            </div>
          </section>

          <div className="timeline-sections">
            {data.correlations.length > 0 && (
              <section className="panel timeline-section timeline-correlations">
                <div className="panel-head">
                  <h2 className="panel-title">Correlated incidents</h2>
                  <span className="panel-count">{correlations.length}</span>
                </div>
                <PillFilter
                  options={RULE_FILTERS}
                  value={ruleFilter}
                  onChange={setRuleFilter}
                  ariaLabel="Filter correlated incidents by rule"
                />
                {correlations.length === 0 && (
                  <div className="empty">No correlations match this filter.</div>
                )}
                {correlations.length > 0 && (
                  <div className="correlation-list">
                    {correlations.map((c) => (
                      <CorrelationRow key={c.correlation_id} correlation={c} />
                    ))}
                  </div>
                )}
              </section>
            )}

            <section className="panel timeline-section timeline-events">
              <div className="panel-head">
                <h2 className="panel-title">Recent events</h2>
                <span className="panel-count">{events.length}</span>
              </div>
              <PillFilter
                options={SEVERITY_FILTERS}
                value={severityFilter}
                onChange={setSeverityFilter}
                ariaLabel="Filter recent events by severity"
              />
              {data.events.length === 0 && <div className="empty">No events yet.</div>}
              {data.events.length > 0 && events.length === 0 && (
                <div className="empty">No events match this filter.</div>
              )}
              {events.length > 0 && (
                <div className="timeline-list">
                  {events.map((evt) => (
                    <TimelineRow key={evt.event_id} evt={evt} />
                  ))}
                </div>
              )}
            </section>
          </div>
        </div>
      )}
    </div>
  );
}

function SummaryStat({
  label,
  value,
  severity,
}: {
  label: string;
  value: string;
  severity?: string;
}) {
  return (
    <div className="summary-stat">
      <span className="summary-stat-label">{label}</span>
      <span className={`summary-stat-value ${severity ? `sev-${severity}` : ""}`}>{value}</span>
    </div>
  );
}

function TimelineRow({ evt }: { evt: TimelineEvent }) {
  return (
    <div className={`timeline-row severity-${evt.severity}`}>
      <span className={`badge badge-${evt.severity}`}>{evt.severity}</span>
      <span className="tl-type">{evt.type}</span>
      <span className="tl-sensor">{evt.sensor_id}</span>
      {evt.escalated && <span className="tl-escalated">escalated</span>}
      <span className="tl-time">{formatTs(evt.source_ts)}</span>
    </div>
  );
}