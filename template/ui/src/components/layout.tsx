// Layouts as data. A screen names its parts once; a layout is an arrangement
// of those names in rows and columns. Layouts can be hand-written, kept in a
// JSON file, or produced by a model for a particular question or data shape:
// `parseLayouts` rejects anything that names a part or grid that does not
// exist, so a generated layout can only rearrange what the screen already has.
import React from "react";
import { cn } from "@/lib/utils";
import type { ViewChoice } from "@/components/views";

export const GRIDS = {
  one: "",
  text: "max-w-[42rem]",
  halves: "md:grid-cols-2",
  thirds: "md:grid-cols-3",
  "main-side": "items-start lg:grid-cols-[minmax(0,1fr)_20rem]",
  "side-main": "items-start lg:grid-cols-[minmax(0,24rem)_minmax(0,1fr)]",
} as const;

export type LayoutRow = { grid: keyof typeof GRIDS; cells: string[][]; stickyFirst?: boolean };
export type LayoutSpec = ViewChoice & { rows: LayoutRow[] };

/** Check untrusted layout data against the parts a screen offers. Throws with a plain message. */
export function parseLayouts(data: unknown, partNames: readonly string[]): LayoutSpec[] {
  const list = Array.isArray(data) ? data : (data as { layouts?: unknown })?.layouts;
  if (!Array.isArray(list) || list.length === 0) throw new Error("A layout file needs a non-empty list of layouts.");
  const seen = new Set<string>();
  return list.map((raw, index) => {
    const spec = raw as Partial<LayoutSpec>;
    const where = `layout ${spec?.key ?? index + 1}`;
    if (!spec || typeof spec.key !== "string" || !/^[a-z][a-z0-9-]*$/.test(spec.key)) throw new Error(`${where}: key must be lowercase letters, digits and hyphens.`);
    if (seen.has(spec.key)) throw new Error(`${where}: key is used twice.`);
    seen.add(spec.key);
    if (typeof spec.label !== "string" || !spec.label.trim()) throw new Error(`${where}: label is required.`);
    if (!Array.isArray(spec.rows) || spec.rows.length === 0) throw new Error(`${where}: at least one row is required.`);
    const used = new Set<string>();
    for (const row of spec.rows) {
      if (!row || !(row.grid in GRIDS)) throw new Error(`${where}: unknown grid "${String(row?.grid)}". Use one of ${Object.keys(GRIDS).join(", ")}.`);
      if (!Array.isArray(row.cells) || row.cells.length === 0) throw new Error(`${where}: a row needs at least one cell.`);
      for (const cell of row.cells) {
        if (!Array.isArray(cell)) throw new Error(`${where}: a cell is a list of part names.`);
        for (const name of cell) {
          if (!partNames.includes(name)) throw new Error(`${where}: unknown part "${String(name)}". This screen has ${partNames.join(", ")}.`);
          if (used.has(name)) throw new Error(`${where}: part "${name}" appears twice.`);
          used.add(name);
        }
      }
    }
    return { key: spec.key, label: spec.label, hint: spec.hint, rows: spec.rows };
  });
}

/** Render one layout. `parts` maps each name to what to draw; a part that returns null takes no space. */
export function Layout({ spec, parts }: { spec: LayoutSpec; parts: Record<string, React.ReactNode> }) {
  return (
    <div className="space-y-5">
      {spec.rows.map((row, rowIndex) => (
        <div key={rowIndex} className={cn("grid gap-5", GRIDS[row.grid])}>
          {row.cells.map((cell, cellIndex) => (
            <div key={cellIndex} className={cn("min-w-0 space-y-5", row.stickyFirst && cellIndex === 0 && "lg:sticky lg:top-4 lg:self-start")}>
              {cell.map((name) => (
                <React.Fragment key={name}>{parts[name]}</React.Fragment>
              ))}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
