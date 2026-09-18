import { useDashboard } from "./hooks/useDashboard";
import { useHashRoute } from "./router";
import { HomePage } from "./pages/HomePage";
import { AllAlarmsPage } from "./pages/AllAlarmsPage";
import { AllSitesPage } from "./pages/AllSitesPage";
import { AllSensorsPage } from "./pages/AllSensorsPage";
import { AllCorrelationsPage } from "./pages/AllCorrelationsPage";

export default function App() {
  const dashboard = useDashboard();
  const route = useHashRoute();

  switch (route.path) {
    case "/alarms":
      return (
        <AllAlarmsPage
          key={route.params.get("status") ?? "active"}
          initialStatus={route.params.get("status")}
          onAcknowledge={dashboard.acknowledge}
          onResolve={dashboard.resolve}
        />
      );
    case "/sites":
      return <AllSitesPage />;
    case "/sensors":
      return (
        <AllSensorsPage
          key={route.params.get("online") ?? "all"}
          initialOnline={route.params.get("online")}
        />
      );
    case "/correlations":
      return <AllCorrelationsPage />;
    default:
      return <HomePage dashboard={dashboard} route={route} />;
  }
}