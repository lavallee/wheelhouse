// Overview: what needs the operator, then the state of the system. The parts
// are named once and arranged by the layouts in overview.layouts.json.
import { Layout, parseLayouts } from "@/components/layout";
import { ViewSwitch, useView } from "@/components/views";
import { Empty, ErrorBanner, Loading, Move, Section, Stat, StatusDot, count, money, stamp } from "@/components/shell";
import { href, type Route } from "@/lib/route";
import layoutData from "@/screens/overview.layouts.json";
import { useResource } from "@/lib/transport";

type Overview = {
  stats: { new: number; held: number; approved: number; rejected: number };
  needs_you: { id: string; title: string; source: string; received: string }[];
  latest_run: { id: string; started: string; status: string; items: number; cost: number } | null;
};

const PARTS = ["waiting", "stats", "latest-run"] as const;
const LAYOUTS = parseLayouts(layoutData, PARTS);

export function OverviewScreen({ route }: { route: Route }) {
  const { view, remember } = useView("overview", LAYOUTS, route.params.get("view"));
  const { data, error, loading, refetch } = useResource<Overview>("/api/overview");
  if (!data) return loading ? <Loading what="overview" /> : <ErrorBanner message={error} onRetry={refetch} />;
  const { stats, needs_you, latest_run } = data;
  const spec = LAYOUTS.find((layout) => layout.key === view.key) ?? LAYOUTS[0];
  const parts = {
    waiting: (
      <Section
        title="Waiting on you"
        description={stats.new ? `${count(stats.new)} submissions have not been reviewed. Oldest first.` : undefined}
        action={stats.new > 0 && <a className="text-xs underline underline-offset-2" href={href("review")}>Review them</a>}
      >
        {needs_you.length === 0 ? (
          <Empty>Nothing is waiting on you.</Empty>
        ) : (
          <ul className="divide-y">
            {needs_you.map((item) => (
              <li key={item.id} className="flex items-center justify-between gap-3 py-2">
                <a href={href("items", [item.id])} className="min-w-0">
                  <span className="block truncate text-sm font-medium">{item.title}</span>
                  <span className="block text-xs text-muted-foreground">{item.source} · received {stamp(item.received)}</span>
                </a>
                <Move who="you" />
              </li>
            ))}
          </ul>
        )}
      </Section>
    ),
    stats: (
      <div className="@container">
      <div className="grid grid-cols-2 gap-3 @2xl:grid-cols-4">
          <Stat label="New" value={count(stats.new)} href={href("items", [], { status: "new" })} />
          <Stat label="Held" value={count(stats.held)} href={href("items", [], { status: "held" })} />
          <Stat label="Approved" value={count(stats.approved)} href={href("items", [], { status: "approved" })} />
          <Stat label="Rejected" value={count(stats.rejected)} href={href("items", [], { status: "rejected" })} />
        </div>
      </div>
    ),
    "latest-run": (
      <Section title="Latest run" action={<a className="text-xs underline underline-offset-2" href={href("runs")}>All runs</a>}>
        {latest_run ? (
          <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
            <StatusDot status={latest_run.status} />
            <span>{stamp(latest_run.started)}</span>
            <span className="tabular-nums">{count(latest_run.items)} items</span>
            <span className="tabular-nums">{money(latest_run.cost)}</span>
          </p>
        ) : (
          <Empty>No run has happened yet.</Empty>
        )}
      </Section>
    ),
  };
  return (
    <>
      <ErrorBanner message={error} onRetry={refetch} />
      <div className="flex justify-end">
        <ViewSwitch views={LAYOUTS} view={view} to={(key) => href("overview", [], { view: key })} onPick={remember} />
      </div>
      <Layout spec={spec} parts={parts} />
    </>
  );
}
