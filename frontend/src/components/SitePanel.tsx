import type { Site } from "../types";
import { SEVERITY_RANK } from "../types";

export function SitePanel({ sites }: { sites: Site[] }) {
  const sorted = [...sites].sort(
    (a, b) =>
      SEVERITY_RANK[b.highest_active_severity ?? "informational"] -
        SEVERITY_RANK[a.highest_active_severity ?? "informational"] || a.site_id.localeCompare(b.site_id),
  );

  return (
    <section className="panel">
      <h2>Site state</h2>
      <div className="site-grid">
        {sorted.map((site) => (
          <div key={site.site_id} className={`site-card sev-${site.highest_active_severity ?? "none"}`}>
            <div className="site-id">{site.site_id}</div>
            <div className="site-count">{site.active_alarm_count} active</div>
            <div className="site-sev">
              {site.highest_active_severity ? site.highest_active_severity : "clear"}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}