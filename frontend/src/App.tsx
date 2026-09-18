import { useState } from "react";
import { useDashboard } from "./hooks/useDashboard";
import { AlarmList } from "./components/AlarmList";
import { SummaryBar } from "./components/SummaryBar";
import { SitePanel } from "./components/SitePanel";
import { SiteTimeline } from "./components/SiteTimeline";
import { SensorPanel } from "./components/SensorPanel";
import { CorrelationPanel } from "./components/CorrelationPanel";

export default function App() {
  const dashboard = useDashboard();
  const [selectedSite, setSelectedSite] = useState<string | null>(null);

  return (
    <div className="app">
      <SummaryBar
        alarms={dashboard.alarms}
        sensors={dashboard.sensors}
        status={dashboard.status}
        latency={dashboard.latency}
      />
      <main className="layout">
        <div className="col-main">
          <AlarmList
            alarms={dashboard.alarms}
            onAcknowledge={dashboard.acknowledge}
            onResolve={dashboard.resolve}
          />
          {selectedSite && (
            <SiteTimeline siteId={selectedSite} onClose={() => setSelectedSite(null)} />
          )}
          <CorrelationPanel correlations={dashboard.correlations} />
        </div>
        <div className="col-side">
          <SitePanel
            sites={dashboard.sites}
            selectedSiteId={selectedSite}
            onSelectSite={setSelectedSite}
          />
          <SensorPanel sensors={dashboard.sensors} />
        </div>
      </main>
    </div>
  );
}