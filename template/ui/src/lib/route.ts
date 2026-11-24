// Hash routes: #view/rest?query. Every page and filter state is a shareable link.
import { useEffect, useState } from "react";

export type Route = { view: string; parts: string[]; params: URLSearchParams };

export function readRoute(): Route {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  const parts = path.split("/").filter(Boolean).map((p) => { try { return decodeURIComponent(p); } catch { return p; } });
  return { view: parts[0] || "overview", parts: parts.slice(1), params: new URLSearchParams(query) };
}

export function useRoute(): Route {
  const [r, setR] = useState(readRoute);
  useEffect(() => {
    // Scroll to the top only when the screen changes. A filter, a page, a view
    // or an open row changes the address too, and must leave the reader in place.
    let view = readRoute().view;
    const f = () => {
      const next = readRoute();
      if (next.view !== view) window.scrollTo(0, 0);
      view = next.view;
      setR(next);
    };
    addEventListener("hashchange", f);
    return () => removeEventListener("hashchange", f);
  }, []);
  return r;
}

export function href(view: string, parts: string[] = [], params?: Record<string, string | string[] | number | undefined | null>): string {
  const p = [view, ...parts.map((x) => encodeURIComponent(x))].join("/");
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) {
    if (v === undefined || v === null || v === "") continue;
    for (const x of Array.isArray(v) ? v : [v]) if (x !== "") q.append(k, String(x));
  }
  const s = q.toString();
  return "#" + p + (s ? "?" + s : "");
}

export function paramsObj(p: URLSearchParams): Record<string, string[]> {
  const o: Record<string, string[]> = {};
  p.forEach((v, k) => { (o[k] ||= []).push(v); });
  return o;
}
