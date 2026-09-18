import { useState } from "react";
import { api } from "../api/client";
import { BrowsePage } from "../components/BrowsePage";
import { AlarmRow } from "../components/AlarmRow";
import { useDebounced } from "../hooks/useDebounced";
import type { Alarm } from "../types";

interface Props {
  initialStatus?: string | null;
  onAcknowledge: (alarm: Alarm) => void;
  onResolve: (alarm: Alarm) => void;
}

const STATUS_OPTIONS = [
  { value: "active", label: "Active (unresolved)" },
  { value: "ACTIVE", label: "ACTIVE" },
  { value: "ACKNOWLEDGED", label: "ACKNOWLEDGED" },
  { value: "RESOLVED", label: "RESOLVED" },
];

export function AllAlarmsPage({ initialStatus, onAcknowledge, onResolve }: Props) {
  const [status, setStatus] = useState(initialStatus ?? "active");
  const [siteInput, setSiteInput] = useState("");
  const site = useDebounced(siteInput.trim());
  const paramsKey = `${status}|${site.toLowerCase()}`;

  return (
    <BrowsePage<Alarm>
      title="All alarms"
      subtitle="Server-side paginated view of the full alarm set."
      filters={({ setPage }) => (
        <>
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
            aria-label="Filter by status"
          >
            {STATUS_OPTIONS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
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
        api.browseAlarms({
          page,
          page_size: pageSize,
          status,
          site_id: site || undefined,
        })
      }
      paramsKey={paramsKey}
      renderRow={(a, ctx) => (
        <AlarmRow
          alarm={a}
          onAcknowledge={async (alarm) => {
            await onAcknowledge(alarm);
            ctx.refetch();
          }}
          onResolve={async (alarm) => {
            await onResolve(alarm);
            ctx.refetch();
          }}
        />
      )}
      rowKey={(a) => a.alarm_id}
      emptyLabel="No alarms match the current filters."
    />
  );
}