import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { SiteTimeline as SiteTimelineData, TimelineEvent } from "../types";

interface Props {
  siteId: string;
  onClose: () => void;
}

export function SiteTimeline({ siteId, onClose }: Props) {
  const [data, setData] = useState<SiteTimelineData | null>(null);
  const [error, setError] = useState<string | null>(null);
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

  if (error) {
    return (
      <section className="panel timeline">
        <div className="timeline-header">
          <h2>Site timeline</h2>
          <button onClick={onClose}>Close</button>
        </div>
        <div className="empty">Failed to load timeline: {error}</div>
      </section>
    );
  }

  if (!data) {
    return (
      <section className="panel timeline">
        <div className="timeline-header">
          <h2>Site timeline</h2>
          <button onClick={onClose}>Close</button>
        </div>
        <div className="empty">Loading {siteId}…</div>
      </section>
    );
  }

  return (
    <section className="panel timeline">
      <div className="timeline-header">
        <h2>
          Site timeline — <span className="site-id">{data.site.site_id}</span>
        </h2>
        <button onClick={onClose}>Close</button>
      </div>

      {data.correlations.length > 0 && (
        <div className="timeline-block">
          <h3>Correlated incidents</h3>
          <div className="correlation-list">
            {data.correlations.map((c) => (
              <div key={c.correlation_id} className={`correlation-row corr-${c.rule}`}>
                <span className="corr-rule">{c.rule}</span>
                <span className="corr-desc">{c.description}</span>
                <span className="corr-sev">
                  {c.severity_before} <span className="corr-arrow">→</span>{" "}
                  {c.severity_after}
                </span>
                <span className="corr-time">{formatTs(c.detected_at)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="timeline-block">
        <h3>Recent events ({data.events.length})</h3>
        <div className="timeline-list">
          {data.events.length === 0 && <div className="empty">No events yet.</div>}
          {data.events.map((evt) => (
            <TimelineRow key={evt.event_id} evt={evt} />
          ))}
        </div>
      </div>
    </section>
  );
}

function TimelineRow({ evt }: { evt: TimelineEvent }) {
  return (
    <div className="timeline-row">
      <span className={`badge badge-${evt.severity}`}>{evt.severity}</span>
      <span className="tl-type">{evt.type}</span>
      <span className="tl-sensor">{evt.sensor_id}</span>
      {evt.escalated && <span className="tl-escalated">escalated</span>}
      <span className="tl-time">{formatTs(evt.source_ts)}</span>
    </div>
  );
}

function formatTs(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleTimeString([], { hour12: false });
}