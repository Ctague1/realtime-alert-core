import type { Site } from "../types";
import { SEVERITY_RANK } from "../types";

const PREVIEW_COUNT = 12;

interface Props {
  sites: Site[];
  /** True count of sites, from /stats. */
  total: number;
  onSelectSite: (siteId: string) => void;
  selectedSiteId: string | null;
  viewAllHref: string;
}

export function SitePanel({ sites, total, onSelectSite, selectedSiteId, viewAllHref }: Props) {
  const sorted = [...sites].sort(
    (a, b) =>
      SEVERITY_RANK[b.highest_active_severity ?? "informational"] -
        SEVERITY_RANK[a.highest_active_severity ?? "informational"] || a.site_id.localeCompare(b.site_id),
  );
  const shown = sorted.slice(0, PREVIEW_COUNT);

  return (
    <section className="panel site-panel">
      <div className="panel-head">
        <h2 className="panel-title">Site state</h2>
        <span className="panel-count">{total.toLocaleString()}</span>
      </div>
      <div className="site-grid">
        {shown.map((site) => (
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
      {total > PREVIEW_COUNT && (
        <a className="panel-more" href={viewAllHref}>
          View all {total.toLocaleString()} sites
        </a>
      )}
    </section>
  );
}