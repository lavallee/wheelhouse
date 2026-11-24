// Settings: one small form per concern, saved by a command, plus commands the
// operator can copy and run themselves.
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CopyLine, ErrorBanner, Loading, Section, Small } from "@/components/shell";
import { command, useResource } from "@/lib/transport";

type Settings = { budget: { dollars_per_run: number; items_per_run: number }; cli: string };

export function SettingsScreen() {
  const { data, error, loading, refetch } = useResource<Settings>("/api/settings", false);
  const [dollars, setDollars] = useState("");
  const [items, setItems] = useState("");
  const [state, setState] = useState<{ saving?: boolean; saved?: boolean; error?: string }>({});
  useEffect(() => {
    if (data) {
      setDollars(String(data.budget.dollars_per_run));
      setItems(String(data.budget.items_per_run));
    }
  }, [data]);
  if (!data) return loading ? <Loading what="settings" /> : <ErrorBanner message={error} onRetry={refetch} />;
  const changed = dollars !== String(data.budget.dollars_per_run) || items !== String(data.budget.items_per_run);
  return (
    <>
      <ErrorBanner message={error} onRetry={refetch} />
      <Section title="Run budget" description="A run that would exceed either limit is refused before it starts.">
        <form
          className="grid max-w-md gap-3"
          onSubmit={async (event) => {
            event.preventDefault();
            setState({ saving: true });
            try {
              // The budget shows only here and on the runs screen; nothing else needs a refetch.
              await command("budget", { dollars_per_run: Number(dollars), items_per_run: Number(items) }, { invalidate: ["/api/settings", "/api/runs"] });
              setState({ saved: true });
            } catch (reason) {
              setState({ error: reason instanceof Error ? reason.message : "Saving did not work." });
            }
          }}
        >
          <label className="grid gap-1 text-xs text-muted-foreground">
            Dollars per run
            <Input className="h-8" inputMode="decimal" value={dollars} onChange={(event) => { setDollars(event.target.value); setState({}); }} />
          </label>
          <label className="grid gap-1 text-xs text-muted-foreground">
            Submissions per run
            <Input className="h-8" inputMode="numeric" value={items} onChange={(event) => { setItems(event.target.value); setState({}); }} />
          </label>
          <ErrorBanner message={state.error} />
          <div className="flex items-center gap-3">
            <Button size="sm" type="submit" disabled={!changed || state.saving}>{state.saving ? "Saving…" : "Save budget"}</Button>
            {state.saved && !changed && <Small role="status">Saved.</Small>}
          </div>
        </form>
      </Section>
      <Section title="From a terminal" description="This admin shows the command; it never runs it for you.">
        <CopyLine value={data.cli} />
      </Section>
    </>
  );
}
