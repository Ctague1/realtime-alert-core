import type { Site } from "../types";
import { SEVERITY_RANK } from "../types";

interface Props {
  sites: Site[];
  onSelectSite: (siteId: string) => void;
  selectedSiteId: string | null;
}

export function SitePanel({ sites, onSelectSite, selectedSiteId }: Props) {
  const sorted = [...sites].sort(
    (a, b) =>
      SEVERITY_RANK[b.highest_active_severity ?? "informational"] -
        SEVERITY_RANK[a.highest_active_severity ?? "informational"] || a.site_id.localeCompare(b.site_id),
  );

  return (
    <section className="panel site-panel">
      <div className="panel-head">
        <h2 className="panel-title">Site state</h2>
        <span className="panel-count">{sites.length}</span>
      </div>
      <div className="site-grid">
        {sorted.map((site) => (
          <button
            key={site.site_id}
            className={`site-card sev-${site.highest_active_severity ?? "none"} ${
              site.site_id === selectedSiteId ? "selected" : ""
            }`}
            onClick={() => onSelectSite(site.site_id)}
            title={`View ${site.site_id} timeline`}
          >
            <div className="site-id">{site.site_id}</div>
            <div className="site-count">{site.active_alarm_count} active</div>
            <div className="site-sev">
              {site.highest_active_severity ? site.highest_active_severity : "clear"}
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}