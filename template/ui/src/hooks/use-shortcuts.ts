// Keyboard shortcuts for a screen. Keys never fire while the user is typing in
// a field, while a modifier is held (unless the binding names it), while a
// dialog is open (it owns the keyboard), or while `enabled` is false. Pass
// `{ inDialogs: true }` for shortcuts that belong to the dialog itself.
import { useEffect, useRef } from "react";

export type Shortcuts = Record<string, (event: KeyboardEvent) => void>;

export function isTyping(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest("input, textarea, select, [contenteditable='true'], [contenteditable='']"));
}

/**
 * Bind keys by `event.key`, lowercased: "j", "1", "escape", " " for space.
 * Prefix with "shift+" for a shifted binding, e.g. "shift+ ".
 */
export function useShortcuts(bindings: Shortcuts, enabled = true, options: { inDialogs?: boolean } = {}): void {
  const latest = useRef(bindings);
  latest.current = bindings;
  const inDialogs = Boolean(options.inDialogs);
  useEffect(() => {
    if (!enabled) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey || isTyping(event.target)) return;
      if (!inDialogs && document.querySelector('[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"], dialog[open]')) return;
      const key = event.key.toLowerCase();
      const handler = (event.shiftKey && latest.current[`shift+${key}`]) || (!event.shiftKey || key.length > 1 || !/[a-z ]/.test(key) ? latest.current[key] : undefined);
      if (handler) {
        event.preventDefault();
        handler(event);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled, inDialogs]);
}
