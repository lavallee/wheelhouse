// A review queue worked one item at a time, by pointer or keyboard. The verbs
// are bounded (approve, hold, reject), each can carry a note, and the last
// decision can be undone.
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Empty, ErrorBanner, Kbd, Kv, Loading, Out, Section, StateBadge, bytes, count, stamp } from "@/components/shell";
import { useShortcuts } from "@/hooks/use-shortcuts";
import { href } from "@/lib/route";
import { command, useResource } from "@/lib/transport";
import type { Item } from "@/screens/items";

const VERBS = [
  { decision: "approve", label: "Approve", key: "a", variant: "default" },
  { decision: "hold", label: "Hold", key: "h", variant: "outline" },
  { decision: "reject", label: "Reject", key: "r", variant: "outline" },
] as const;
type Decision = (typeof VERBS)[number]["decision"];

async function decide(id: string, decision: Decision | "reopen", note: string) {
  return command("review", { id, decision, note });
}

/** The three verbs and a note field. Used in the queue and in the detail sheet. */
export function ReviewActions({ item, onDone, shortcuts }: { item: Item; onDone?: (decision: string) => void; shortcuts?: boolean }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const act = async (decision: Decision | "reopen") => {
    if (busy) return;
    setBusy(decision);
    setError("");
    try {
      await decide(item.id, decision, note);
      setNote("");
      onDone?.(decision);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "That did not work.");
    } finally {
      setBusy("");
    }
  };
  useShortcuts(Object.fromEntries(VERBS.map((verb) => [verb.key, () => act(verb.decision)])), Boolean(shortcuts) && item.status === "new");

  if (item.status !== "new") {
    return (
      <div className="space-y-2">
        <ErrorBanner message={error} />
        <p className="text-sm text-muted-foreground">Already {item.status}{item.reviewed_by ? ` by ${item.reviewed_by}` : ""}.</p>
        <Button size="sm" variant="outline" disabled={Boolean(busy)} onClick={() => act("reopen")}>Reopen</Button>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <ErrorBanner message={error} />
      <label className="grid gap-1 text-xs text-muted-foreground">
        Note (optional)
        <Input className="h-8" value={note} onChange={(event) => setNote(event.target.value)} />
      </label>
      <div className="flex flex-wrap gap-2">
        {VERBS.map((verb) => (
          <Button key={verb.decision} size="sm" variant={verb.variant} disabled={Boolean(busy)} onClick={() => act(verb.decision)}>
            {busy === verb.decision ? "Saving…" : verb.label}
            {shortcuts && <Kbd className="ml-1">{verb.key.toUpperCase()}</Kbd>}
          </Button>
        ))}
      </div>
    </div>
  );
}

export function ReviewScreen() {
  const { data, error, loading, refetch } = useResource<{ items: Item[]; total: number }>("/api/queue");
  const [last, setLast] = useState<{ id: string; title: string; decision: string } | null>(null);
  const [undoError, setUndoError] = useState("");
  if (!data) return loading ? <Loading what="queue" /> : <ErrorBanner message={error} onRetry={refetch} />;
  const item = data.items[0];
  return (
    <>
      <ErrorBanner message={error || undoError} onRetry={refetch} />
      {last && (
        <p role="status" className="flex flex-wrap items-center gap-2 text-sm">
          <span>"{last.title}" marked {last.decision === "approve" ? "approved" : last.decision === "hold" ? "held" : "rejected"}.</span>
          <Button size="xs" variant="outline" onClick={async () => {
            try { await decide(last.id, "reopen", ""); setLast(null); setUndoError(""); } catch (reason) { setUndoError(reason instanceof Error ? reason.message : "Undo did not work."); }
          }}>Undo</Button>
        </p>
      )}
      {!item ? (
        <Empty>The queue is empty.</Empty>
      ) : (
        <Section title={item.title} description={`${count(data.total)} left · oldest first`} action={<StateBadge value={item.status} />}>
          <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_18rem]">
            <Kv rows={[
              ["Id", <a className="underline underline-offset-2" href={href("items", [item.id])}>{item.id}</a>],
              ["Source", item.source],
              ["Kind", item.kind],
              ["Received", stamp(item.received)],
              ["Size", bytes(item.size)],
              ["Link", <Out href={item.url} />],
              ["Note", item.note],
            ]} />
            <ReviewActions key={item.id} item={item} shortcuts onDone={(decision) => setLast({ id: item.id, title: item.title, decision })} />
          </div>
        </Section>
      )}
    </>
  );
}
