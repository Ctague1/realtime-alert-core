import { useDashboard } from "./hooks/useDashboard";
import { AlarmList } from "./components/AlarmList";
import { SummaryBar } from "./components/SummaryBar";
import { SitePanel } from "./components/SitePanel";
import { SensorPanel } from "./components/SensorPanel";

export default function App() {
  const dashboard = useDashboard();

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
        </div>
        <div className="col-side">
          <SitePanel sites={dashboard.sites} />
          <SensorPanel sensors={dashboard.sensors} />
        </div>
      </main>
    </div>
  );
}