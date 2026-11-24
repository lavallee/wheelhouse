// Run history, and starting a run behind a confirmation that states its cost.
// One run opens in its own scope: the sidebar lists its sections (summary,
// submissions, log) with a link back to all runs.
import { useState } from "react";
import { FileText, Inbox, ScrollText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ConfirmDialog, Empty, ErrorBanner, Kv, Loading, Section, StateBadge, StatusDot, count, money, stamp } from "@/components/shell";
import { useTitle, type NavScope } from "@/components/frame";
import { href, type Route } from "@/lib/route";
import { command, useResource } from "@/lib/transport";
import type { Item } from "@/screens/items";

type Run = { id: string; started: string; status: string; items: number; cost: number; started_by: string };
type Runs = { runs: Run[]; estimate: { items: number; cost: number }; budget: { dollars_per_run: number } };

export function RunsScreen() {
  const { data, error, loading, refetch } = useResource<Runs>("/api/runs");
  const [confirming, setConfirming] = useState(false);
  if (!data) return loading ? <Loading what="runs" /> : <ErrorBanner message={error} onRetry={refetch} />;
  const over = data.estimate.cost > data.budget.dollars_per_run;
  return (
    <>
      <ErrorBanner message={error} onRetry={refetch} />
      <Section title="Runs" description="Newest first." action={<Button size="sm" onClick={() => setConfirming(true)}>Start a run</Button>}>
        {data.runs.length === 0 ? (
          <Empty>No run has happened yet.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Started</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Items</TableHead>
                  <TableHead className="text-right">Cost</TableHead>
                  <TableHead>Started by</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.runs.map((run) => (
                  <TableRow key={run.id}>
                    <TableCell className="py-1.5 tabular-nums">
                      <a href={href("runs", [run.id])} className="underline underline-offset-2 hover:no-underline">
                        {stamp(run.started)}
                      </a>
                    </TableCell>
                    <TableCell className="py-1.5"><StatusDot status={run.status} /></TableCell>
                    <TableCell className="py-1.5 text-right tabular-nums">{count(run.items)}</TableCell>
                    <TableCell className="py-1.5 text-right tabular-nums">{money(run.cost)}</TableCell>
                    <TableCell className="py-1.5 text-muted-foreground">{run.started_by}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Section>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Start a run?"
        confirmLabel="Start the run"
        consequence={
          <>
            This will process about {count(data.estimate.items)} submissions and is estimated to cost {money(data.estimate.cost)}.
            {over ? ` That is over the ${money(data.budget.dollars_per_run)} per-run budget, so the run will be refused.` : ` The per-run budget is ${money(data.budget.dollars_per_run)}.`}
          </>
        }
        onConfirm={() => command("run", {})}
      />
    </>
  );
}

// --- one run --------------------------------------------------------------------

type LogLine = { at: string; level: string; text: string };
type RunDetail = { run: Run; items: Item[]; log: LogLine[] };

const SECTIONS = [
  { id: "summary", label: "Summary", icon: FileText },
  { id: "submissions", label: "Submissions", icon: Inbox },
  { id: "log", label: "Log", icon: ScrollText },
];

/** The sidebar inside one run. `#runs/<id>/<section>`. */
export function runScope(route: Route): NavScope | null {
  const id = route.parts[0];
  if (!id) return null;
  return {
    title: id,
    kind: "Run",
    back: { label: "All runs", href: href("runs") },
    items: SECTIONS.map((section) => ({ ...section, href: href("runs", section.id === "summary" ? [id] : [id, section.id]) })),
    active: route.parts[1] || "summary",
  };
}

export function RunsRoute({ route }: { route: Route }) {
  return route.parts[0] ? <RunScreen id={route.parts[0]} section={route.parts[1] || "summary"} /> : <RunsScreen />;
}

function RunScreen({ id, section }: { id: string; section: string }) {
  const { data, error, missing, loading, refetch } = useResource<RunDetail>(`/api/runs/${encodeURIComponent(id)}`);
  const label = SECTIONS.find((s) => s.id === section)?.label;
  useTitle(label ? `${id} / ${label}` : id);
  if (missing) return <Empty>There is no run {id}. <a className="underline" href={href("runs")}>See all runs</a>.</Empty>;
  if (!data) return loading ? <Loading what="the run" /> : <ErrorBanner message={error} onRetry={refetch} />;
  const { run, items, log } = data;
  const errors = log.filter((line) => line.level === "error").length;
  return (
    <>
      <ErrorBanner message={error} onRetry={refetch} />
      {section === "summary" && (
        <Section title="Summary">
          <Kv
            rows={[
              ["Status", <StatusDot status={run.status} />],
              ["Started", stamp(run.started)],
              ["Started by", run.started_by],
              ["Submissions", count(run.items)],
              ["Cost", money(run.cost)],
              ["Log", `${count(log.length)} lines${errors ? `, ${errors} error${errors === 1 ? "" : "s"}` : ""}`],
            ]}
          />
        </Section>
      )}
      {section === "submissions" && (
        <Section title="Submissions" description={`The ${count(items.length)} submissions this run processed.`}>
          {items.length === 0 ? (
            <Empty>This run processed no submissions.</Empty>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Id</TableHead>
                    <TableHead>Title</TableHead>
                    <TableHead className="hidden sm:table-cell">Source</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell className="py-1.5 font-mono text-xs">
                        <a href={href("items", [item.id])} className="underline underline-offset-2 hover:no-underline">{item.id}</a>
                      </TableCell>
                      <TableCell className="max-w-36 truncate py-1.5 sm:max-w-72">{item.title}</TableCell>
                      <TableCell className="hidden py-1.5 text-muted-foreground sm:table-cell">{item.source}</TableCell>
                      <TableCell className="py-1.5"><StateBadge value={item.status} /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </Section>
      )}
      {section === "log" && (
        <Section title="Log" description="Oldest first, as the run wrote it.">
          {log.length === 0 ? (
            <Empty>This run wrote no log.</Empty>
          ) : (
            <ol className="max-h-[70svh] overflow-y-auto rounded-md border bg-muted/30 p-2 font-mono text-xs leading-relaxed">
              {log.map((line, index) => (
                <li key={index} className={line.level === "error" ? "text-destructive" : undefined}>
                  <span className="text-muted-foreground tabular-nums">{line.at.slice(11, 19)}</span> {line.text}
                </li>
              ))}
            </ol>
          )}
        </Section>
      )}
    </>
  );
}
