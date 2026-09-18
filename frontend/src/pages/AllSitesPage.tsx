import { useState } from "react";
import { api } from "../api/client";
import { BrowsePage } from "../components/BrowsePage";
import { SiteCard } from "../components/SiteCard";
import type { Site } from "../types";

const SEVERITY_OPTIONS = [
  { value: "all", label: "All severities" },
  { value: "critical", label: "Critical" },
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
  { value: "clear", label: "Clear" },
];

export function AllSitesPage() {
  const [severity, setSeverity] = useState("all");
  const paramsKey = severity;

  return (
    <BrowsePage<Site>
      title="All sites"
      subtitle="Complete site state, paginated. Click a site to open its timeline."
      filters={({ setPage }) => (
        <select
          value={severity}
          onChange={(e) => {
            setSeverity(e.target.value);
            setPage(1);
          }}
          aria-label="Filter by severity"
        >
          {SEVERITY_OPTIONS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      )}
      fetcher={(page, pageSize) =>
        api.browseSites({
          page,
          page_size: pageSize,
          severity: severity === "all" ? undefined : severity,
        })
      }
      paramsKey={paramsKey}
      listClassName="browse-sites"
      renderRow={(site) => <SiteCard site={site} />}
      rowKey={(s) => s.site_id}
      emptyLabel="No sites match the current filter."
    />
  );
}