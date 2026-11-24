// Transport for a Wheelhouse admin client. The app id comes from app.config.ts.
//
// Same-origin only: every read goes through `readJSON`, which refuses any path
// that is not a rooted `/api/...` path, and every write goes through `command`,
// which sends the three headers the API requires (X-Requested-With, the CSRF
// token from GET /api/session, and a fresh Idempotency-Key).
//
// Reads are conditional (If-None-Match / 304) and repeat every 15 seconds while
// the screen that asked for them is mounted. A command clears the cached ETags
// of the reads it names (all of them unless told otherwise) and those mounted
// reads refetch at once.
//
// Event streams (`useStream`) reconnect with backoff and resume from the last
// event id. They are the fast path; the poll stays as the fallback.
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { APP } from "@/app.config";

const CLIENT = `${APP.id}-admin`;

/** A 404 is often a real state ("nothing generated yet"), so screens can tell it apart. */
export class NotFound extends Error {
  name = "NotFound";
}

export const POLL_MS = 15000;

export type Session = {
  actor?: string;
  groups?: string[];
  csrf?: string;
  [key: string]: unknown;
};

export type Json = Record<string, unknown>;

const etags = new Map<string, string>();
const bodies = new Map<string, unknown>();

/** Refuse anything that is not a rooted same-origin API path. */
function apiPath(path: string): string {
  if (!path.startsWith("/api/") && path !== "/api") {
    throw new Error(`Refused: ${path} is not a same-origin /api path`);
  }
  return path;
}

export function query(params: Record<string, string | undefined | null>): string {
  const parts = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

export async function readJSON<T = unknown>(path: string, signal?: AbortSignal): Promise<T> {
  const url = apiPath(path);
  const previous = etags.get(url);
  const response = await fetch(url, {
    credentials: "same-origin",
    redirect: "manual",
    signal,
    headers: {
      Accept: "application/json",
      "X-Requested-With": CLIENT,
      ...(previous ? { "If-None-Match": previous } : {}),
    },
  });
  if (response.status === 304 && bodies.has(url)) return bodies.get(url) as T;
  if (response.status === 401 || response.status === 403) {
    throw new Error("Session unavailable or expired. Reload to sign in again.");
  }
  if (response.status === 404) throw new NotFound(`Not found: ${path}`);
  if (response.status === 503) throw new Error("The service is not ready yet.");
  if (!response.ok) {
    // Prefer the API's own words ({"error": "..."}) over a bare status line.
    let said = "";
    try {
      const body = (await response.json()) as { error?: unknown; detail?: unknown };
      said = typeof body?.error === "string" ? body.error : typeof body?.detail === "string" ? body.detail : "";
    } catch {
      said = "";
    }
    throw new Error(said || `${path} — ${response.status} ${response.statusText || "request failed"}`);
  }
  const value = (await response.json()) as T;
  const tag = response.headers.get("etag");
  if (tag) {
    etags.set(url, tag);
    bodies.set(url, value);
  } else {
    etags.delete(url);
    bodies.delete(url);
  }
  return value;
}

// --- revision store: a command refetches the reads it may have changed --------

const listeners = new Set<() => void>();
let revision = 0;

/** Each mounted `useResource`, so an invalidation can reach only the reads it names. */
type Watcher = { path: string; bump: () => void };
const watchers = new Set<Watcher>();

function covers(path: string, prefixes: string[] | null): boolean {
  return prefixes === null || prefixes.some((prefix) => path.startsWith(prefix));
}

/**
 * Forget cached ETags and refetch mounted reads at once. With no argument,
 * every read; with a prefix (or several), only reads whose path starts with
 * one, so `invalidate("/api/items")` refetches `/api/items?…` and
 * `/api/items/SUB-1` but not `/api/runs`.
 */
export function invalidate(prefix?: string | string[]): void {
  const prefixes = prefix === undefined ? null : (Array.isArray(prefix) ? prefix : [prefix]).map(apiPath);
  for (const key of [...etags.keys()]) {
    if (covers(key, prefixes)) {
      etags.delete(key);
      bodies.delete(key);
    }
  }
  revision += 1;
  for (const listener of listeners) listener();
  for (const watcher of watchers) if (covers(watcher.path, prefixes)) watcher.bump();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

const readRevision = () => revision;

export function useRevision(): number {
  return useSyncExternalStore(subscribe, readRevision, readRevision);
}

// --- session ------------------------------------------------------------------

let sessionValue: Session | null = null;
let sessionRequest: Promise<Session> | null = null;

export function loadSession(force = false): Promise<Session> {
  if (force) {
    sessionValue = null;
    sessionRequest = null;
  }
  if (sessionValue) return Promise.resolve(sessionValue);
  if (!sessionRequest) {
    sessionRequest = readJSON<Session>("/api/session")
      .then((value) => {
        sessionValue = value || {};
        return sessionValue;
      })
      .catch((error) => {
        sessionRequest = null;
        throw error;
      });
  }
  return sessionRequest;
}

export function useSession(): { session: Session | null; error: string } {
  const [session, setSession] = useState<Session | null>(sessionValue);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    loadSession()
      .then((value) => {
        if (live) {
          setSession(value);
          setError("");
        }
      })
      .catch((reason) => {
        if (live) setError(reason instanceof Error ? reason.message : "Session unavailable");
      });
    return () => {
      live = false;
    };
  }, []);
  return { session, error };
}

// --- commands -----------------------------------------------------------------

function idempotencyKey(): string {
  const source = globalThis.crypto;
  if (source && typeof source.randomUUID === "function") return source.randomUUID();
  return `${APP.id}-${Date.now().toString(16)}-${Math.random().toString(16).slice(2, 10)}`;
}

export type CommandOptions = {
  /**
   * Which reads to refetch after success: omitted, every mounted read (as
   * before); a path prefix or a list of them, only those; `false`, none, for a
   * command that saves nothing a screen shows.
   */
  invalidate?: false | string | string[];
  /** `false` is the same as `invalidate: false`: for a screen that patches its own state from the result. */
  refetch?: boolean;
};

/** POST /api/commands/<name>. Returns the parsed body; throws with the API's message. */
export async function command(name: string, body: Json, options: CommandOptions = {}): Promise<Json> {
  const session = await loadSession();
  const response = await fetch(apiPath(`/api/commands/${name}`), {
    method: "POST",
    credentials: "same-origin",
    redirect: "manual",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      "X-Requested-With": CLIENT,
      "X-CSRF-Token": String(session?.csrf ?? ""),
      "Idempotency-Key": idempotencyKey(),
    },
    body: JSON.stringify(body),
  });
  let payload: Json = {};
  try {
    payload = ((await response.json()) as Json) || {};
  } catch {
    payload = {};
  }
  if (response.status === 401 || response.status === 403) {
    // A rejected CSRF token is usually a rotated session; drop ours and say so.
    loadSession(true).catch(() => {});
    throw new Error(String(payload.error || payload.detail || "Session expired. Reload and try again."));
  }
  if (!response.ok) {
    throw new Error(String(payload.error || payload.detail || `Command failed (${response.status})`));
  }
  if (options.refetch === false || options.invalidate === false) {
    // nothing to refetch
  } else if (options.invalidate === undefined) invalidate();
  else invalidate(options.invalidate);
  return payload;
}

// --- reads --------------------------------------------------------------------

export type Resource<T> = {
  data: T | null;
  error: string;
  /** True when the last read was a 404: a real state, not a failure. */
  missing: boolean;
  /**
   * True while `data` still belongs to the previous path (a new id or filter is
   * loading). Keep showing it for a list; hide it for a detail record.
   */
  stale: boolean;
  loading: boolean;
  refetch: () => void;
};

/**
 * Read `path` now, whenever an invalidation covers it, and every 15 seconds
 * while mounted. Pass `null` to hold off (an unselected detail route).
 */
export function useResource<T = unknown>(path: string | null, poll = true, every: number = POLL_MS): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [missing, setMissing] = useState(false);
  const [loading, setLoading] = useState(Boolean(path));
  const [nonce, setNonce] = useState(0);
  const [rev, setRev] = useState(0);
  const [loadedPath, setLoadedPath] = useState<string | null>(null);
  const seen = useRef(false);

  useEffect(() => {
    if (!path) return;
    const watcher: Watcher = { path, bump: () => setRev((value) => value + 1) };
    watchers.add(watcher);
    return () => {
      watchers.delete(watcher);
    };
  }, [path]);

  useEffect(() => {
    if (!path) {
      setData(null);
      setError("");
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    let running = false;
    seen.current = false;
    setLoading(true);
    async function refresh() {
      if (running) return;
      running = true;
      try {
        const value = await readJSON<T>(path!, controller.signal);
        if (controller.signal.aborted) return;
        seen.current = true;
        setData(value);
        setLoadedPath(path);
        setError("");
        setMissing(false);
      } catch (reason) {
        if (controller.signal.aborted) return;
        if (reason instanceof NotFound) {
          // Whatever was last shown stays; the screen decides what a 404 means here.
          setMissing(true);
          setError("");
          return;
        }
        // Keep the last good rows on screen; the banner says the refresh failed.
        setError(reason instanceof Error ? reason.message : "Refresh unavailable");
      } finally {
        running = false;
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    refresh();
    const timer = poll ? window.setInterval(refresh, every) : 0;
    const onFocus = () => refresh();
    window.addEventListener("focus", onFocus);
    return () => {
      controller.abort();
      if (timer) window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [path, poll, every, nonce, rev]);

  const refetch = useCallback(() => setNonce((value) => value + 1), []);
  return { data, error, missing, stale: data !== null && loadedPath !== path, loading, refetch };
}

// --- event streams ------------------------------------------------------------

export type StreamEvent = { id: string; event: string; data: string };
export type StreamState = "idle" | "connecting" | "connected" | "reconnecting";

export type StreamOptions = {
  /** Called for every event, in order. The latest function is always used. */
  onEvent: (event: StreamEvent) => void;
  /** Resume after this id on the first connection (sent as `?after=`). */
  after?: string;
  /** Event names to listen for besides plain `message` events. */
  events?: string[];
};

const STREAM_BACKOFF_MS = [1000, 2000, 5000, 10000, 30000];

/**
 * An `EventSource` on a same-origin `/api` stream that reconnects with backoff
 * and resumes from the last id it saw (`?after=<id>`). `EventSource` sends the
 * session cookie but cannot send custom headers, so a stream is guarded like a
 * read and can never be a command. Pass `null` to hold off.
 *
 * The stream is the fast path only: keep polling reads as the fallback, so a
 * blocked or buffered stream makes the screen slow, not wrong.
 */
export function useStream(path: string | null, options: StreamOptions): { state: StreamState; lastId: string } {
  const [state, setState] = useState<StreamState>(path ? "connecting" : "idle");
  const [lastId, setLastId] = useState(options.after ?? "");
  const latest = useRef(options);
  latest.current = options;
  const names = (options.events ?? []).join("\n");

  useEffect(() => {
    if (!path) {
      setState("idle");
      return;
    }
    const base = apiPath(path);
    let source: EventSource | null = null;
    let timer = 0;
    let attempt = 0;
    let closed = false;
    let resumeFrom = latest.current.after ?? "";

    const deliver = (message: MessageEvent) => {
      if (message.lastEventId) {
        resumeFrom = message.lastEventId;
        setLastId(message.lastEventId);
      }
      latest.current.onEvent({ id: message.lastEventId, event: message.type, data: String(message.data ?? "") });
    };

    const open = () => {
      const url = resumeFrom ? `${base}${base.includes("?") ? "&" : "?"}after=${encodeURIComponent(resumeFrom)}` : base;
      source = new EventSource(url);
      source.onopen = () => {
        attempt = 0;
        setState("connected");
      };
      source.onmessage = deliver;
      for (const name of names ? names.split("\n") : []) source.addEventListener(name, deliver as EventListener);
      // A dropped connection, a refused one, and the server's own `event: error`
      // all land here. Reconnect ourselves so the backoff and the resume id are ours.
      source.onerror = () => {
        source?.close();
        source = null;
        if (closed) return;
        setState("reconnecting");
        const wait = STREAM_BACKOFF_MS[Math.min(attempt, STREAM_BACKOFF_MS.length - 1)];
        attempt += 1;
        timer = window.setTimeout(open, wait);
      };
    };

    setState("connecting");
    open();
    return () => {
      closed = true;
      window.clearTimeout(timer);
      source?.close();
    };
  }, [path, names]);

  return { state, lastId };
}

// --- defensive shaping --------------------------------------------------------

/** Rows out of anything: a list, `{items: []}`, `{rows: []}`, or a named key. */
export function rows<T = Record<string, unknown>>(value: unknown, ...keys: string[]): T[] {
  if (Array.isArray(value)) return value as T[];
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    for (const key of [...keys, "items", "rows", "results", "data"]) {
      if (Array.isArray(record[key])) return record[key] as T[];
    }
  }
  return [];
}

/** First defined value at any of these dotted paths. */
export function pick<T = unknown>(source: unknown, ...paths: string[]): T | undefined {
  for (const path of paths) {
    let value: unknown = source;
    for (const part of path.split(".")) {
      if (value === null || value === undefined || typeof value !== "object") {
        value = undefined;
        break;
      }
      value = (value as Record<string, unknown>)[part];
    }
    if (value !== undefined && value !== null) return value as T;
  }
  return undefined;
}

export function text(value: unknown, fallback = ""): string {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "string") return value || fallback;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

export function num(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

export function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}
