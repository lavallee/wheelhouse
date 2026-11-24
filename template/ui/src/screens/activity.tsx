// The activity journal: one event stream per tab, shown in the frame's aside
// and summarised in its status line. Each new entry also refetches the reads it
// may have changed, so another person's decision shows without waiting for the
// poll; the poll stays as the fallback if the stream is blocked.
import { useRef, useState } from "react";
import { Empty, stamp } from "@/components/shell";
import { href } from "@/lib/route";
import { invalidate, useStream, type StreamState } from "@/lib/transport";

export type Activity = { seq: number; at: string; actor: string; verb: string; target: string; title: string };

const KEEP = 60;
/** The reads a journal entry can change. */
const TOUCHES = ["/api/overview", "/api/queue", "/api/items", "/api/runs"];

export function useActivity(): { rows: Activity[]; state: StreamState; fresh: number } {
  const [rows, setRows] = useState<Activity[]>([]);
  // A ref, not state: a backlog and its `ready` can arrive before React re-renders.
  const ready = useRef(false);
  const [fresh, setFresh] = useState(0);
  const { state } = useStream("/api/activity/stream", {
    events: ["activity", "ready"],
    onEvent: (event) => {
      if (event.event === "ready") {
        // Caught up: anything missed while away may have changed what is on screen.
        if (ready.current) invalidate(TOUCHES);
        ready.current = true;
        return;
      }
      let row: Activity;
      try {
        row = JSON.parse(event.data) as Activity;
      } catch {
        return;
      }
      setRows((current) => (current.some((r) => r.seq === row.seq) ? current : [row, ...current].slice(0, KEEP)));
      if (ready.current) {
        setFresh((n) => n + 1);
        invalidate(TOUCHES);
      }
    },
  });
  return { rows, state, fresh };
}

export function activityStatus(state: StreamState): string {
  if (state === "connected") return "Live · changes appear as they happen";
  if (state === "reconnecting") return "Reconnecting to live changes · still checking for updates every 15 seconds";
  return "Connecting to live changes…";
}

function targetHref(target: string): string | null {
  if (target.startsWith("SUB-")) return href("items", [target]);
  if (target.startsWith("RUN-")) return href("runs", [target]);
  if (target === "budget") return href("settings");
  return null;
}

export function ActivityList({ rows }: { rows: Activity[] }) {
  if (rows.length === 0) return <Empty>Nothing has happened yet. Decisions and runs appear here as they are made.</Empty>;
  return (
    <ol className="divide-y text-xs">
      {rows.map((row) => {
        const to = targetHref(row.target);
        return (
          <li key={row.seq} className="grid gap-0.5 py-2 first:pt-0">
            <span className="flex items-baseline justify-between gap-2">
              <span className="min-w-0 truncate">
                <span className="text-muted-foreground">{row.actor.replace(/^human:/, "")}</span> {row.verb}{" "}
                {to ? (
                  <a href={to} className="font-mono underline underline-offset-2 hover:no-underline">
                    {row.target}
                  </a>
                ) : (
                  <span className="font-mono">{row.target}</span>
                )}
              </span>
              <time className="shrink-0 tabular-nums text-muted-foreground" dateTime={row.at}>
                {stamp(row.at)}
              </time>
            </span>
            <span className="truncate text-muted-foreground">{row.title}</span>
          </li>
        );
      })}
    </ol>
  );
}

export function activitySummary(rows: Activity[], fresh: number): string {
  const latest = rows[0];
  if (!latest) return "Nothing yet";
  const line = `${latest.actor.replace(/^human:/, "")} ${latest.verb} ${latest.target}`;
  return fresh ? `${fresh} new · ${line}` : line;
}
