import type { Site } from "../types";
import { SEVERITY_RANK } from "../types";
import { SiteCard } from "./SiteCard";

const PREVIEW_COUNT = 12;

interface Props {
  sites: Site[];
  /** True count of sites, from /stats. */
  total: number;
  viewAllHref: string;
}

export function SitePanel({ sites, total, viewAllHref }: Props) {
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
          <SiteCard key={site.site_id} site={site} />
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