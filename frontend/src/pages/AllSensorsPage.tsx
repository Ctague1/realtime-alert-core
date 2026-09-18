import { useState } from "react";
import { api } from "../api/client";
import { BrowsePage } from "../components/BrowsePage";
import { useDebounced } from "../hooks/useDebounced";
import { ago } from "../lib/format";
import type { Sensor } from "../types";

interface Props {
  initialOnline?: string | null;
}

const ONLINE_OPTIONS = [
  { value: "all", label: "All sensors" },
  { value: "online", label: "Online" },
  { value: "offline", label: "Offline" },
];

export function AllSensorsPage({ initialOnline }: Props) {
  const [online, setOnline] = useState(initialOnline ?? "all");
  const [siteInput, setSiteInput] = useState("");
  const site = useDebounced(siteInput.trim());
  const paramsKey = `${online}|${site.toLowerCase()}`;

  return (
    <BrowsePage<Sensor>
      title="All sensors"
      subtitle="Complete sensor fleet, paginated."
      filters={({ setPage }) => (
        <>
          <select
            value={online}
            onChange={(e) => {
              setOnline(e.target.value);
              setPage(1);
            }}
            aria-label="Filter by online status"
          >
            {ONLINE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
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
        api.browseSensors({
          page,
          page_size: pageSize,
          site_id: site || undefined,
          online: online === "all" ? null : online === "online",
        })
      }
      paramsKey={paramsKey}
      renderRow={(s) => (
        <div className={`sensor-row ${s.online ? "" : "sensor-row-offline"}`}>
          <span className="tl-sensor">{s.sensor_id}</span>
          <span>site {s.site_id}</span>
          {s.latest_event_type && <span className="tl-type">{s.latest_event_type}</span>}
          <span className={`badge ${s.online ? "badge-low" : "badge-critical"}`}>
            {s.online ? "online" : "offline"}
          </span>
          <span className="tl-time">last event {ago(s.last_event_ts)}</span>
        </div>
      )}
      rowKey={(s) => s.sensor_id}
      emptyLabel="No sensors match the current filters."
    />
  );
}