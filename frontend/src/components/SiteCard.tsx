import type { Site } from "../types";

export function SiteCard({ site }: { site: Site }) {
  return (
    <a
      className={`site-card sev-${site.highest_active_severity ?? "none"}`}
      href={`#/sites/${encodeURIComponent(site.site_id)}`}
      title={`View ${site.site_id} timeline`}
    >
      <div className="site-id">{site.site_id}</div>
      <div className="site-count">{site.active_alarm_count} active</div>
      <div className="site-sev">
        {site.highest_active_severity ? site.highest_active_severity : "clear"}
      </div>
    </a>
  );
}