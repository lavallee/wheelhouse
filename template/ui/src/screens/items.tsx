// A filtered, sortable, server-paged list with a detail sheet. Every filter,
// the page, the view and the open row live in the address, so any state is a
// link. Below `md` the table becomes two-line rows.
import { useEffect, useState } from "react";
import { Input } from "@/components/ui/input";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";
import { Empty, ErrorBanner, Kv, Loading, Out, Pager, SortHead, StateBadge, bytes, count, stamp } from "@/components/shell";
import { useTitle } from "@/components/frame";
import { ViewSwitch, useView } from "@/components/views";
import { href, type Route } from "@/lib/route";
import { query, useResource } from "@/lib/transport";
import type { SortState } from "@/hooks/use-sortable";
import { ReviewActions } from "@/screens/review";

export type Item = { id: string; title: string; source: string; kind: string; status: string; received: string; size: number; url: string; note: string; reviewed_by: string | null };
type Page = { items: Item[]; total: number; limit: number; offset: number; facets: { status: Record<string, number>; source: Record<string, number> } };

const VIEWS = [
  { key: "table", label: "Table", hint: "One row per submission, sortable" },
  { key: "by-source", label: "By source", hint: "The same page of results grouped by where they came from" },
];
const LIMIT = 25;

export function ItemsScreen({ route }: { route: Route }) {
  const p = route.params;
  const filters = { status: p.get("status") ?? "", source: p.get("source") ?? "", q: p.get("q") ?? "", sort: p.get("sort") ?? "" };
  const page = Math.max(1, Number(p.get("page")) || 1);
  const openId = route.parts[0] ?? "";
  const { view, remember } = useView("items", VIEWS, p.get("view"));

  const link = (change: Record<string, string | number | undefined>, parts: string[] = route.parts) =>
    href("items", parts, { ...filters, page: page > 1 ? page : undefined, view: p.get("view") ?? undefined, ...change });
  const go = (change: Record<string, string | number | undefined>) => { location.hash = link({ page: undefined, ...change }); };

  const { data, error, loading, refetch } = useResource<Page>(`/api/items${query({ ...filters, limit: String(LIMIT), offset: String((page - 1) * LIMIT) })}`);

  // The search box types locally and commits to the address after a pause.
  const [draft, setDraft] = useState(filters.q);
  useEffect(() => setDraft(filters.q), [filters.q]);
  useEffect(() => {
    if (draft === filters.q) return;
    const timer = window.setTimeout(() => go({ q: draft }), 300);
    return () => window.clearTimeout(timer);
  });

  const sort: SortState = filters.sort ? { key: filters.sort.replace(/^-/, ""), dir: filters.sort.startsWith("-") ? "desc" : "asc" } : null;
  const onSort = (key: string) => go({ sort: sort?.key !== key ? key : sort.dir === "asc" ? `-${key}` : undefined });
  const anyFilter = filters.status || filters.source || filters.q;
  const items = data?.items ?? [];
  const groups = view.key === "by-source" ? [...new Set(items.map((item) => item.source))].map((source) => [source, items.filter((item) => item.source === source)] as const) : [];

  return (
    <>
      <ErrorBanner message={error} onRetry={refetch} />
      <div className="flex flex-wrap items-end gap-2">
        <label className="grid gap-1 text-xs text-muted-foreground">
          Search
          <Input className="h-8 w-56" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Title or note" />
        </label>
        <label className="grid gap-1 text-xs text-muted-foreground">
          Status
          <NativeSelect size="sm" value={filters.status} onChange={(event) => go({ status: event.target.value })}>
            <NativeSelectOption value="">All</NativeSelectOption>
            {Object.entries(data?.facets.status ?? {}).map(([value, n]) => <NativeSelectOption key={value} value={value}>{value} ({n})</NativeSelectOption>)}
          </NativeSelect>
        </label>
        <label className="grid gap-1 text-xs text-muted-foreground">
          Source
          <NativeSelect size="sm" value={filters.source} onChange={(event) => go({ source: event.target.value })}>
            <NativeSelectOption value="">All</NativeSelectOption>
            {Object.entries(data?.facets.source ?? {}).map(([value, n]) => <NativeSelectOption key={value} value={value}>{value} ({n})</NativeSelectOption>)}
          </NativeSelect>
        </label>
        {anyFilter && <a className="pb-1.5 text-xs underline underline-offset-2" href={href("items", [], { view: p.get("view") ?? undefined })}>Clear filters</a>}
        <div className="ml-auto"><ViewSwitch views={VIEWS} view={view} to={(key) => link({ view: key })} onPick={remember} /></div>
      </div>

      {!data ? (loading ? <Loading what="submissions" /> : null) : items.length === 0 ? (
        <Empty>{anyFilter ? "No submissions match these filters." : "No submissions yet."}</Empty>
      ) : view.key === "by-source" ? (
        <div className="space-y-4">
          {groups.map(([source, list]) => (
            <section key={source} aria-label={source}>
              <h2 className="mb-1 text-xs font-medium text-muted-foreground">{source} · {list.length} on this page</h2>
              <Rows items={list} link={link} />
            </section>
          ))}
        </div>
      ) : (
        <>
          <div className="hidden md:block">
            <Table className="table-fixed">
              <TableHeader>
                <TableRow>
                  <SortHead label="Submission" sortKey="title" sort={sort} onSort={onSort} />
                  <SortHead label="Source" sortKey="source" sort={sort} onSort={onSort} className="w-40" />
                  <SortHead label="Received" sortKey="received" sort={sort} onSort={onSort} className="w-40" />
                  <SortHead label="Size" sortKey="size" sort={sort} onSort={onSort} className="w-24 text-right [&>button]:flex-row-reverse" />
                  <SortHead label="Status" sortKey="status" sort={sort} onSort={onSort} className="w-28" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((item) => (
                  <TableRow key={item.id} data-state={openId === item.id ? "selected" : undefined}>
                    <TableCell className="truncate py-1.5"><a className="font-medium hover:underline" href={link({}, [item.id])}>{item.title}</a></TableCell>
                    <TableCell className="truncate py-1.5 text-muted-foreground">{item.source}</TableCell>
                    <TableCell className="py-1.5 tabular-nums text-muted-foreground">{stamp(item.received)}</TableCell>
                    <TableCell className="py-1.5 text-right tabular-nums">{bytes(item.size)}</TableCell>
                    <TableCell className="py-1.5"><StateBadge value={item.status} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="md:hidden"><Rows items={items} link={link} /></div>
        </>
      )}
      {data && data.total > 0 && <Pager page={page} pages={Math.ceil(data.total / LIMIT)} total={data.total} to={(n) => link({ page: n > 1 ? n : undefined })} />}
      <ItemSheet id={openId} onClose={() => { location.hash = link({}, []); }} />
    </>
  );
}

/** Two-line rows: the phone form of the table, and the body of a grouped view. */
function Rows({ items, link }: { items: Item[]; link: (change: Record<string, string | number | undefined>, parts?: string[]) => string }) {
  return (
    <ul className="divide-y">
      {items.map((item) => (
        <li key={item.id}>
          <a href={link({}, [item.id])} className="flex items-center justify-between gap-3 py-2">
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium">{item.title}</span>
              <span className="block truncate text-xs text-muted-foreground">{item.source} · {stamp(item.received)} · {bytes(item.size)}</span>
            </span>
            <StateBadge value={item.status} />
          </a>
        </li>
      ))}
    </ul>
  );
}

function ItemSheet({ id, onClose }: { id: string; onClose: () => void }) {
  const { data, error, missing, loading } = useResource<{ item: Item }>(id ? `/api/items/${encodeURIComponent(id)}` : null);
  const item = data?.item;
  useTitle(item?.title);
  return (
    <Sheet open={Boolean(id)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full gap-0 overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{item?.title ?? (missing ? "Not found" : id)}</SheetTitle>
          <SheetDescription>{item ? `${item.id} · ${item.kind}` : missing ? `There is no submission ${id}.` : "Loading…"}</SheetDescription>
        </SheetHeader>
        <div className="space-y-5 px-4 pb-6">
          <ErrorBanner message={error} />
          {loading && !item && <Loading what="submission" />}
          {item && (
            <>
              <Kv rows={[
                ["Status", <StateBadge value={item.status} />],
                ["Source", item.source],
                ["Received", stamp(item.received)],
                ["Size", `${bytes(item.size)} (${count(item.size)} bytes)`],
                ["Link", <Out href={item.url} />],
                ["Reviewed by", item.reviewed_by],
                ["Note", item.note],
              ]} />
              <ReviewActions item={item} />
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
