// Alternate views of one screen. The choice is remembered per screen and kept
// in the address, and the control stays small and out of the way. Whatever is
// selected or filtered belongs to the screen, not the view, so it carries across.
import { useCallback, useState } from "react";
import { cn } from "@/lib/utils";

export type ViewChoice = { key: string; label: string; hint?: string };

/**
 * `screen` names the storage slot. `current` is the view named in the address,
 * if any; `fallback` picks one when nothing is stored (for example by screen width).
 */
export function useView(screen: string, views: ViewChoice[], current: string | null, fallback?: () => string) {
  const slot = `view:${screen}`;
  const valid = (key: string | null | undefined) => views.find((view) => view.key === key);
  const [stored, setStored] = useState(() => {
    try {
      return localStorage.getItem(slot);
    } catch {
      return null;
    }
  });
  const view = valid(current) ?? valid(stored) ?? valid(fallback?.()) ?? views[0];
  const remember = useCallback(
    (key: string) => {
      setStored(key);
      try {
        localStorage.setItem(slot, key);
      } catch {
        /* private mode: the address still carries the choice */
      }
    },
    [slot],
  );
  return { view, remember };
}

/** A small segmented control. `to` returns the link for a view, so the choice is shareable. */
export function ViewSwitch({ views, view, to, onPick }: { views: ViewChoice[]; view: ViewChoice; to: (key: string) => string; onPick: (key: string) => void }) {
  return (
    <nav aria-label="View" className="inline-flex shrink-0 items-center rounded-lg border p-0.5 text-xs">
      {views.map((choice) => (
        <a
          key={choice.key}
          href={to(choice.key)}
          title={choice.hint}
          aria-current={choice.key === view.key ? "true" : undefined}
          onClick={() => onPick(choice.key)}
          className={cn(
            "rounded-md px-2 py-1 text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
            choice.key === view.key && "bg-muted font-medium text-foreground",
          )}
        >
          {choice.label}
        </a>
      ))}
    </nav>
  );
}
