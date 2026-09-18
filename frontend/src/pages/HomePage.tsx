import { useState } from "react";
import { SummaryBar } from "../components/SummaryBar";
import { AlarmList } from "../components/AlarmList";
import { SitePanel } from "../components/SitePanel";
import { SiteTimeline } from "../components/SiteTimeline";
import { SensorPanel } from "../components/SensorPanel";
import { CorrelationPanel } from "../components/CorrelationPanel";
import { setHash, type Route } from "../router";
import type { Dashboard } from "../hooks/useDashboard";

interface Props {
  dashboard: Dashboard;
  route: Route;
}

export function HomePage({ dashboard, route }: Props) {
  const [selectedSite, setSelectedSite] = useState<string | null>(() => route.params.get("site"));
  const stats = dashboard.stats;

  const fallbackOffline = dashboard.sensors.filter((s) => !s.online).length;
  const offlineCount = stats?.sensors_offline ?? fallbackOffline;
  const onlineCount = stats
    ? stats.sensors_total - stats.sensors_offline
    : dashboard.sensors.length - fallbackOffline;

  const handleSelectSite = (siteId: string) => {
    setSelectedSite(siteId);
    setHash(`/?site=${encodeURIComponent(siteId)}`);
  };
  const handleCloseTimeline = () => {
    setSelectedSite(null);
    setHash("/");
  };

  return (
    <div className="app">
      <SummaryBar stats={stats} status={dashboard.status} latency={dashboard.latency} />
      <main className="layout">
        <div className="col-main">
          <AlarmList
            alarms={dashboard.alarms}
            total={stats?.alarms_active ?? dashboard.alarms.length}
            onAcknowledge={dashboard.acknowledge}
            onResolve={dashboard.resolve}
            viewAllHref="#/alarms?status=active"
          />
          {selectedSite && (
            <SiteTimeline siteId={selectedSite} onClose={handleCloseTimeline} />
          )}
          <CorrelationPanel
            correlations={dashboard.correlations}
            total={stats?.correlations_total ?? dashboard.correlations.length}
            viewAllHref="#/correlations"
          />
        </div>
        <div className="col-side">
          <SitePanel
            sites={dashboard.sites}
            total={stats?.sites_total ?? dashboard.sites.length}
            selectedSiteId={selectedSite}
            onSelectSite={handleSelectSite}
            viewAllHref="#/sites"
          />
          <SensorPanel
            sensors={dashboard.sensors}
            onlineCount={onlineCount}
            offlineCount={offlineCount}
            viewAllOfflineHref="#/sensors?online=false"
          />
        </div>
      </main>
    </div>
  );
}