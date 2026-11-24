// Shared furniture: the small set of compositions every admin screen reuses so
// task anatomy stays in the same place from route to route.
import React, { useState } from "react";
import { AlertTriangle, Check, ChevronLeft, ChevronRight, Copy, ExternalLink } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { TableHead } from "@/components/ui/table";
import type { SortState } from "@/hooks/use-sortable";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const Small = ({ children, className, ...props }: React.ComponentProps<"p">) => (
  <p className={cn("text-xs text-muted-foreground", className)} {...props}>
    {children}
  </p>
);

export function Section({
  title,
  description,
  action,
  children,
  id,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
  children?: React.ReactNode;
  id?: string;
}) {
  return (
    <Card className="gap-4 py-4" id={id}>
      <CardHeader className="px-4">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="text-sm">{title}</CardTitle>
          {action}
        </div>
        {description && <CardDescription className="text-xs">{description}</CardDescription>}
      </CardHeader>
      <CardContent className="px-4">{children}</CardContent>
    </Card>
  );
}

export function Stat({
  label,
  value,
  note,
  href,
  selected,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  note?: React.ReactNode;
  href?: string;
  /** Marks the stat whose filter is applied. */
  selected?: boolean;
}) {
  const body = (
    <>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-xl font-semibold tabular-nums">{value}</p>
      {note && <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{note}</p>}
    </>
  );
  if (href) {
    return (
      <a href={href} aria-current={selected ? "true" : undefined} className={cn("block rounded-md border bg-card p-3 hover:bg-accent", selected && "ring-1 ring-foreground")}>
        {body}
      </a>
    );
  }
  return <div className={cn("rounded-md border bg-card p-3", selected && "ring-1 ring-foreground")}>{body}</div>;
}

export function ErrorBanner({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  if (!message) return null;
  return (
    <div
      role="status"
      className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs"
    >
      <span className="flex items-center gap-2">
        <AlertTriangle className="size-3.5 shrink-0" aria-hidden="true" />
        {message}
      </span>
      {onRetry && (
        <Button size="sm" variant="outline" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}

/** A plain notice that is not an error: a pending state, a caveat, a result. */
export function Notice({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div role="status" className="flex flex-wrap items-center justify-between gap-2 rounded-md border bg-muted/40 px-3 py-2 text-xs">
      <span>{children}</span>
      {action}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="rounded-md border border-dashed px-3 py-6 text-center text-xs text-muted-foreground">{children}</p>;
}

export function Loading({ what }: { what: string }) {
  return <Small>Loading {what}…</Small>;
}

/** A link out of the admin, marked as leaving. Renders plain text for non-URLs. */
export function Out({ href, children }: { href?: unknown; children?: React.ReactNode }) {
  const url = typeof href === "string" ? href.trim() : "";
  const label = children ?? url;
  if (!url) return <>{label}</>;
  const external = /^https?:\/\//i.test(url);
  if (!external && !url.startsWith("/") && !url.startsWith("./") && !url.startsWith("#")) {
    // A filesystem path, not a link. Show it as what it is.
    return <code className="text-xs text-muted-foreground">{label}</code>;
  }
  return (
    <a
      href={url}
      className="inline-flex items-baseline gap-1 underline underline-offset-2 hover:no-underline"
      {...(external ? { target: "_blank", rel: "noreferrer noopener" } : {})}
    >
      {label}
      {external && <ExternalLink className="size-3 shrink-0 self-center" aria-hidden="true" />}
    </a>
  );
}

/** Copyable text the operator runs themselves; the UI never executes it. */
export function CopyLine({ value, label }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-start gap-2">
      <code className="min-w-0 flex-1 overflow-x-auto rounded-md border bg-muted/50 px-2 py-1.5 text-xs whitespace-pre">
        {value}
      </code>
      <Button
        size="sm"
        variant="outline"
        aria-label={label || "Copy command"}
        onClick={() => {
          navigator.clipboard?.writeText(value).then(
            () => {
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1500);
            },
            () => setCopied(false),
          );
        }}
      >
        {copied ? <Check className="size-3.5" aria-hidden="true" /> : <Copy className="size-3.5" aria-hidden="true" />}
        <span className="sr-only sm:not-sr-only">{copied ? "Copied" : "Copy"}</span>
      </Button>
    </div>
  );
}

type BadgeVariant = "default" | "secondary" | "outline" | "destructive" | "warning";

/**
 * Common states. An app adds its own words with `registerStates`, and should
 * also pin any word below that it already shows in a different style: these
 * defaults otherwise restyle it (one adopting admin showed "open" as an
 * outline badge).
 */
const statusVariants: Record<string, BadgeVariant> = {
  new: "default",
  open: "default",
  high: "default",
  active: "secondary",
  approved: "secondary",
  ok: "secondary",
  done: "secondary",
  medium: "secondary",
  held: "outline",
  paused: "outline",
  parked: "outline",
  retired: "outline",
  low: "outline",
  rejected: "destructive",
  failed: "destructive",
  halted: "destructive",
  error: "destructive",
};

export function registerStates(states: Record<string, BadgeVariant>): void {
  Object.assign(statusVariants, states);
}

export function StateBadge({ value, className }: { value: unknown; className?: string }) {
  const label = typeof value === "string" ? value : value === null || value === undefined ? "" : String(value);
  if (!label) return <span className="text-muted-foreground">—</span>;
  // The whole phrase wins over its first word, so "browser queue" and "browser active" can differ.
  const phrase = label.toLowerCase().trim();
  const variant = statusVariants[phrase] || statusVariants[phrase.split(/[\s(]/)[0]] || "outline";
  const warning = variant === "warning";
  return (
    <Badge variant={warning ? "outline" : variant} className={cn("font-normal", warning && "border-amber-500/60 text-amber-700 dark:text-amber-400", className)}>
      {label}
    </Badge>
  );
}

export function Chips({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-wrap gap-1">{children}</div>;
}

// --- formatting ---------------------------------------------------------------

export const dash = "—";

export function money(value: unknown): string {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return dash;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: n % 1 === 0 ? 0 : 2,
  }).format(n);
}

export function count(value: unknown): string {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n.toLocaleString("en-US") : dash;
}

function parseDate(value: unknown): Date | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00` : value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function daysUntil(value: unknown): number | null {
  const when = parseDate(value);
  if (!when) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  when.setHours(0, 0, 0, 0);
  return Math.round((when.getTime() - today.getTime()) / 86400000);
}

export function daysSince(value: unknown): number | null {
  const days = daysUntil(value);
  return days === null ? null : -days;
}

export function stamp(value: unknown): string {
  const when = parseDate(value);
  if (!when) return typeof value === "string" && value ? value : dash;
  return when.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function day(value: unknown): string {
  const when = parseDate(value);
  if (!when) return typeof value === "string" && value ? value : dash;
  return when.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

/** "in 4 days" / "3 days ago" / "today", with the raw date kept alongside. */
export function DeadlineCell({ value }: { value: unknown }) {
  const days = daysUntil(value);
  if (!value) return <span className="text-muted-foreground">{dash}</span>;
  if (days === null) return <span>{String(value)}</span>;
  const relative = days === 0 ? "today" : days > 0 ? `in ${days}d` : `${-days}d ago`;
  return (
    <span className="whitespace-nowrap">
      <span className="tabular-nums">{day(value)}</span>{" "}
      <span className={days < 0 ? "text-muted-foreground line-through" : "text-muted-foreground"}>{relative}</span>
    </span>
  );
}

export function bytes(value: unknown): string {
  if (value === null || value === undefined || value === "") return dash;
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return dash;
  const gb = n / 1e9;
  if (Math.abs(gb) >= 1000) return `${(n / 1e12).toLocaleString("en-US", { maximumFractionDigits: 2 })} TB`;
  if (Math.abs(gb) >= 1) return `${gb.toLocaleString("en-US", { maximumFractionDigits: 1 })} GB`;
  const mb = n / 1e6;
  if (Math.abs(mb) >= 1) return `${mb.toLocaleString("en-US", { maximumFractionDigits: 1 })} MB`;
  if (Math.abs(n) >= 1000) return `${(n / 1e3).toLocaleString("en-US", { maximumFractionDigits: 0 })} KB`;
  return `${n.toLocaleString("en-US")} B`;
}

// --- tables ---------------------------------------------------------------------

/** A clickable table header: first click sorts ascending, second descending,
 * third clears back to the screen's default order. */
export function SortHead({
  label,
  sortKey,
  sort,
  onSort,
  className,
}: {
  label: React.ReactNode;
  sortKey: string;
  sort: SortState;
  onSort: (key: string) => void;
  className?: string;
}) {
  const active = sort?.key === sortKey;
  const dir = active && sort ? sort.dir : null;
  return (
    <TableHead className={className} {...(active ? { "aria-sort": dir === "asc" ? "ascending" : "descending" } : {})}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={cn(
          "inline-flex items-center gap-1 rounded-sm font-medium whitespace-nowrap underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
          active ? "text-foreground" : "hover:text-foreground",
        )}
      >
        {label}
        {active && (
          <span aria-hidden="true" className="text-xs leading-none">
            {dir === "asc" ? "▲" : "▼"}
          </span>
        )}
      </button>
    </TableHead>
  );
}

/** Previous / next for a server-paged list. `to` returns the link for a page. */
export function Pager({ page, pages, total, to, size = "xs" }: { page: number; pages: number; total: number; to: (page: number) => string; size?: "xs" | "sm" }) {
  const last = Math.max(pages, 1);
  return (
    <div className={cn("flex items-center justify-between gap-2 text-muted-foreground", size === "sm" ? "text-sm" : "text-xs")}>
      <span className="tabular-nums">
        {count(total)} results · page {page} of {last}
      </span>
      <div className="flex gap-1">
        <Button variant="outline" size="sm" asChild className={page <= 1 ? "pointer-events-none opacity-40" : ""}>
          <a href={to(page - 1)} aria-label="Previous page" aria-disabled={page <= 1} tabIndex={page <= 1 ? -1 : undefined}>
            <ChevronLeft aria-hidden="true" />
          </a>
        </Button>
        <Button variant="outline" size="sm" asChild className={page >= last ? "pointer-events-none opacity-40" : ""}>
          <a href={to(page + 1)} aria-label="Next page" aria-disabled={page >= last} tabIndex={page >= last ? -1 : undefined}>
            <ChevronRight aria-hidden="true" />
          </a>
        </Button>
      </div>
    </div>
  );
}

// --- small parts ----------------------------------------------------------------

/** Label and value pairs for a detail sheet or page. Empty values show a dash. */
export function Kv({ rows, stack }: { rows: [React.ReactNode, React.ReactNode][]; /** Stack label over value below `sm`, for phone-first screens. */ stack?: boolean }) {
  return (
    <dl className={cn("grid gap-x-4 gap-y-1.5 text-sm", stack ? "grid-cols-1 sm:grid-cols-[11rem_1fr] [&>dd]:mb-1.5 sm:[&>dd]:mb-0" : "grid-cols-[max-content_1fr]")}>
      {rows.map(([label, value], index) => (
        <React.Fragment key={index}>
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="min-w-0 break-words">{value === null || value === undefined || value === "" ? <span className="text-muted-foreground">{dash}</span> : value}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

const statusDots: Record<string, string> = {
  ok: "bg-emerald-500",
  running: "bg-sky-500",
  failed: "bg-red-500",
  gone: "bg-red-500",
  unreachable: "bg-amber-500",
};

/** An app adds its own dot words; pass a Tailwind background class for each. */
export function registerStatusDots(dots: Record<string, string>): void {
  Object.assign(statusDots, dots);
}

/** A coloured dot plus the word, so state never rests on colour alone. */
export function StatusDot({ status }: { status: unknown }) {
  const key = typeof status === "string" ? status.toLowerCase() : "";
  if (!key) return <span className="text-muted-foreground">{dash}</span>;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs whitespace-nowrap">
      <span className={cn("size-2 shrink-0 rounded-full", statusDots[key] || "bg-muted-foreground/40")} aria-hidden="true" />
      {key}
    </span>
  );
}

/** A slim usage bar: `value` against `max`, clamped, marked when over. */
export function UsageBar({ value, max, label, className }: { value: number; max: number; label?: string; className?: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  const over = max > 0 && value > max;
  return (
    <div className={cn("h-2 w-full overflow-hidden rounded-full bg-muted", className)} role="img" aria-label={label ?? `${Math.round(max > 0 ? (value / max) * 100 : 0)}% used`}>
      <div className={cn("h-full rounded-full", over ? "bg-destructive" : "bg-primary")} style={{ width: `${pct}%` }} />
    </div>
  );
}

/** Who has to act next on a row or card. */
export function Move({ who }: { who: "you" | "agent" | "nobody" }) {
  if (who === "nobody") return null;
  return <Badge variant={who === "you" ? "default" : "outline"}>{who === "you" ? "Your move" : "Agent's move"}</Badge>;
}

/**
 * Confirmation for an action with a cost or consequence. The body says what
 * will happen; the confirm button repeats the verb. Errors stay in the dialog.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  consequence,
  confirmLabel,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  consequence: React.ReactNode;
  confirmLabel: string;
  onConfirm: () => Promise<unknown>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!busy) {
          setError("");
          onOpenChange(next);
        }
      }}
    >
      <DialogContent className="sm:max-w-[52ch]">
        <DialogHeader>
          <DialogTitle className="text-sm">{title}</DialogTitle>
          <DialogDescription asChild>
            <div className="text-sm leading-relaxed">{consequence}</div>
          </DialogDescription>
        </DialogHeader>
        <ErrorBanner message={error} />
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" size="sm" disabled={busy}>
              Cancel
            </Button>
          </DialogClose>
          <Button
            size="sm"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setError("");
              try {
                await onConfirm();
                onOpenChange(false);
              } catch (reason) {
                setError(reason instanceof Error ? reason.message : "That did not work.");
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Working…" : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// --- form and keyboard parts -----------------------------------------------------

/** A key name on a control, so shortcuts are visible where they act. */
export function Kbd({ children, className }: { children: React.ReactNode; className?: string }) {
  return <kbd className={cn("inline-flex min-w-5 items-center justify-center rounded border px-1 font-sans text-xs font-normal text-muted-foreground", className)}>{children}</kbd>;
}

/** A labelled control. The label wraps the control, so no id wiring is needed. */
export function Field({ label, hint, children, className }: { label: React.ReactNode; hint?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <label className={cn("grid gap-1 text-xs text-muted-foreground", className)}>
      <span>{label}</span>
      {children}
      {hint && <span>{hint}</span>}
    </label>
  );
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.ComponentProps<"textarea">>(function Textarea({ className, ...props }, ref) {
  return (
    <textarea
      ref={ref}
      className={cn(
        "min-h-16 w-full rounded-md border border-input bg-transparent px-2.5 py-1.5 text-sm text-foreground outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50 dark:bg-input/30",
        className,
      )}
      {...props}
    />
  );
});

/** Detail that is one click away, using the native element so it works without script. */
export function Disclosure({ summary, children, className, open }: { summary: React.ReactNode; children: React.ReactNode; className?: string; open?: boolean }) {
  return (
    <details open={open} className={cn("rounded-md border px-3 py-2 text-sm", className)}>
      <summary className="cursor-pointer font-medium focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">{summary}</summary>
      <div className="mt-2 space-y-2">{children}</div>
    </details>
  );
}
