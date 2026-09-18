import { SummaryBar } from "../components/SummaryBar";
import { AlarmList } from "../components/AlarmList";
import { SitePanel } from "../components/SitePanel";
import { SensorPanel } from "../components/SensorPanel";
import { CorrelationPanel } from "../components/CorrelationPanel";
import type { Dashboard } from "../hooks/useDashboard";

interface Props {
  dashboard: Dashboard;
}

export function HomePage({ dashboard }: Props) {
  const stats = dashboard.stats;

  const fallbackOffline = dashboard.sensors.filter((s) => !s.online).length;
  const offlineCount = stats?.sensors_offline ?? fallbackOffline;
  const onlineCount = stats
    ? stats.sensors_total - stats.sensors_offline
    : dashboard.sensors.length - fallbackOffline;

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