// Per-table sort state: click a header to sort ascending, click again for
// descending, a third click returns to the screen's default order. Null,
// missing, and blank values sort as empty (ahead of everything else).
import { useMemo, useState } from "react";

export type SortDir = "asc" | "desc";
export type SortState = { key: string; dir: SortDir } | null;

/** Numbers and booleans compare natively; everything else compares as a
 * case-insensitive string with numeric awareness ("v2" < "v10"). */
export function compareCells(a: unknown, b: unknown): number {
  const blank = (v: unknown) =>
    v === null || v === undefined || (typeof v === "string" && v.trim() === "");
  if (blank(a) && blank(b)) return 0;
  if (blank(a)) return -1;
  if (blank(b)) return 1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  if (typeof a === "boolean" && typeof b === "boolean") return Number(a) - Number(b);
  return String(a).localeCompare(String(b), "en", { numeric: true, sensitivity: "base" });
}

export function useSortable<T extends Record<string, unknown>>(items: T[]): {
  sorted: T[];
  sort: SortState;
  toggleSort: (key: string) => void;
} {
  const [sort, setSort] = useState<SortState>(null);

  const sorted = useMemo(() => {
    if (!sort) return items;
    const { key, dir } = sort;
    const sign = dir === "asc" ? 1 : -1;
    // Array.prototype.sort is stable, so ties keep the default order.
    return [...items].sort((a, b) => sign * compareCells(a[key], b[key]));
  }, [items, sort]);

  const toggleSort = (key: string) =>
    setSort((prev) =>
      prev?.key === key ? (prev.dir === "asc" ? { key, dir: "desc" } : null) : { key, dir: "asc" },
    );

  return { sorted, sort, toggleSort };
}
