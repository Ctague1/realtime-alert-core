import { useDashboard } from "./hooks/useDashboard";
import { useHashRoute } from "./router";
import { HomePage } from "./pages/HomePage";
import { AllAlarmsPage } from "./pages/AllAlarmsPage";
import { AllSitesPage } from "./pages/AllSitesPage";
import { AllSensorsPage } from "./pages/AllSensorsPage";
import { AllCorrelationsPage } from "./pages/AllCorrelationsPage";
import { SiteTimelinePage } from "./pages/SiteTimelinePage";

export default function App() {
  const dashboard = useDashboard();
  const route = useHashRoute();
  const path = route.path;

  if (path.startsWith("/sites/")) {
    const siteId = decodeURIComponent(path.slice("/sites/".length));
    return siteId ? <SiteTimelinePage key={siteId} siteId={siteId} /> : <AllSitesPage />;
  }

  switch (path) {
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
      return <HomePage dashboard={dashboard} />;
  }
}