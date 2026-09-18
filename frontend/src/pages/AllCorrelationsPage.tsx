import { useState } from "react";
import { api } from "../api/client";
import { BrowsePage } from "../components/BrowsePage";
import { CorrelationRow } from "../components/CorrelationRow";
import { useDebounced } from "../hooks/useDebounced";
import type { Correlation } from "../types";

const RULE_OPTIONS = [
  { value: "all", label: "All rules" },
  { value: "repeat_event", label: "Repeat event" },
  { value: "multi_signal_site", label: "Multi-signal site" },
  { value: "critical_burst", label: "Critical burst" },
];

export function AllCorrelationsPage() {
  const [rule, setRule] = useState("all");
  const [siteInput, setSiteInput] = useState("");
  const site = useDebounced(siteInput.trim());
  const paramsKey = `${rule}|${site.toLowerCase()}`;

  return (
    <BrowsePage<Correlation>
      title="All correlations"
      subtitle="Detected patterns & escalations, paginated."
      filters={({ setPage }) => (
        <>
          <select
            value={rule}
            onChange={(e) => {
              setRule(e.target.value);
              setPage(1);
            }}
            aria-label="Filter by rule"
          >
            {RULE_OPTIONS.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
          <input
            type="search"
            placeholder="Filter by site id"
            value={siteInput}
            onChange={(e) => setSiteInput(e.target.value)}
            aria-label="Filter by site"
          />
        </>
      )}
      fetcher={(page, pageSize) =>
        api.browseCorrelations({
          page,
          page_size: pageSize,
          site_id: site || undefined,
          rule: rule === "all" ? undefined : rule,
        })
      }
      paramsKey={paramsKey}
      renderRow={(c) => <CorrelationRow correlation={c} />}
      rowKey={(c) => c.correlation_id}
      emptyLabel="No correlations match the current filters."
    />
  );
}