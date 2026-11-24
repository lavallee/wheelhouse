# Working on this admin

- Shared parts live in `ui/src/components/` (`shell.tsx`, `frame.tsx`,
  `views.tsx`, `ui/`), `ui/src/lib/` and `ui/src/hooks/`. Change them in the
  Wheelhouse registry, not here; `wheelhouse drift ui` shows local edits.
- A screen reads with `useResource("/api/...")` and writes with
  `command("name", body)`. Do not call `fetch` directly. A command refetches
  every mounted read unless given `{ invalidate: "/api/prefix" }` (or a list,
  or `false` when it saves nothing a screen shows).
- Live changes come over one event stream per tab (`useStream`), opened in
  `main.tsx`. Each event says what changed; refetch those reads with
  `invalidate(prefix)`. The poll stays on as the fallback.
- Frame slots: `group` and `scope` on a nav item, and `status` and `aside` on
  `AppFrame`. A record with sections of its own gets a `scope`, not a tab bar.
- Every filter, page, view and open row belongs in the address (`href(...)`),
  so any state can be linked.
- Keep the last good data on screen when a refresh fails; `ErrorBanner` says so.
- An action with a cost or a consequence goes through `ConfirmDialog`, which
  states what will happen.
- Check a change in a browser at 1440 and 390 wide with the sample data's
  volume before calling it done.
