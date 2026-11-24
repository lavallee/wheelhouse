import { createRoot } from "react-dom/client";
import { Activity as ActivityIcon, Inbox, LayoutDashboard, ListChecks, Play, Settings, Ship } from "lucide-react";
import { AppFrame, type NavItem } from "@/components/frame";
import { ActivityList, activityStatus, activitySummary, useActivity } from "@/screens/activity";
import { OverviewScreen } from "@/screens/overview";
import { ItemsScreen } from "@/screens/items";
import { ReviewScreen } from "@/screens/review";
import { RunsRoute, runScope } from "@/screens/runs";
import { SettingsScreen } from "@/screens/settings";
import "./index.css";

// An admin is its nav. Add a screen by adding a line here; `group` puts it
// under a label, `scope` gives a record its own sections.
const nav: NavItem[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard, group: "Work", render: (route) => <OverviewScreen route={route} /> },
  { id: "review", label: "Review", icon: ListChecks, group: "Work", render: () => <ReviewScreen /> },
  { id: "items", label: "Submissions", icon: Inbox, group: "Work", render: (route) => <ItemsScreen route={route} /> },
  { id: "runs", label: "Runs", icon: Play, group: "System", render: (route) => <RunsRoute route={route} />, scope: runScope },
  { id: "settings", label: "Settings", icon: Settings, group: "System", render: () => <SettingsScreen /> },
];

function App() {
  // One stream per tab: the activity aside and the status line share it.
  const { rows, state, fresh } = useActivity();
  return (
    <AppFrame
      nav={nav}
      icon={Ship}
      liveNote={activityStatus(state)}
      aside={{ label: "Activity", icon: ActivityIcon, summary: activitySummary(rows, fresh), render: () => <ActivityList rows={rows} /> }}
    />
  );
}

createRoot(document.getElementById("root")!).render(<App />);
