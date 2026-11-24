# wheelhouse

A shared template for internal admin tools: one set of interface parts, one
backend contract, and one command to start a new admin.

"Wheelhouse" is a working name. MIT licensed; see `LICENSE`.

| Path | What it is |
|---|---|
| `template/` | A complete, running admin: `ui/` (React 19, Vite, Tailwind 4, shadcn) and `backend/` (Python). New admins are copies of it |
| `template/ui/registry.json` | The list of shared parts, as a shadcn registry manifest |
| `registry/r/` | The built registry (`npx shadcn build`), ready to serve over HTTP |
| `python/` | The `wheelhouse` package: identity providers, command guard, idempotency, ETags, paging, event streams, lifespan hooks, and the CLI. Its README is the wire contract |
| `scripts/hygiene.py` | Refuses private names, local paths and private hostnames in anything tracked; run by `ci.sh` |
| `shots/` | Captures of the template at 1440 and 390 wide |

## Start a new admin

```console
$ git clone https://github.com/lavallee/wheelhouse && cd wheelhouse/python && uv sync
$ uv run wheelhouse new intake --name "Intake" --tagline "submission review" --dir ../../intake --port 8961
$ cd ../../intake && ./ci.sh && ./dev.sh
```

`new`, `drift` and `sync` read the template from the checkout they run in, so
they work from a clone, not from an installed package.

The new admin runs at once on sample data, with an overview, a review queue,
a filtered list with a detail sheet, run history with one run in its own
scoped nav, settings, and a live activity aside. Replace `backend/sample.py`
with the real store and edit the screens.

The new admin depends on the `wheelhouse` package from this repository by git,
at the tag of the version that created it (`--rev` picks another). To work
against this checkout instead (before a release is tagged, or to try a change),
pass `--wheelhouse .` from `python/`, or any path to a checkout's `python/`: it
is written relative to the new admin, never as an absolute path.

To add the backend package to an existing app:

```toml
[project]
dependencies = ["wheelhouse"]

[tool.uv.sources]
wheelhouse = { git = "https://github.com/lavallee/wheelhouse", subdirectory = "python", rev = "v0.1.0" }
```

The interface parts are copied, not installed: `wheelhouse sync` (below), or
the files under `template/ui/src` by hand.

## Keep an admin in step

```console
$ uv run wheelhouse drift ../../intake/ui                          # what differs from the shared parts
$ uv run wheelhouse sync  ../../intake/ui shell transport          # dry run
$ uv run wheelhouse sync  ../../intake/ui shell transport --write
```

`drift` compares the stock primitives and the shared parts (theme, transport,
route, sorting, shell, frame, view switch, layouts). It ignores `screen-*`
items, which are starting points.

## Where the parts came from

Every shared part was taken from the better of two or more working admin
tools that had each grown its own copy, then tidied: the theme and primitives
were already byte-identical across six of them; the transport, routes,
sorting, shell parts, frame and backend guard each come from the strongest
copy, with the weaknesses listed in `python/README.md` fixed. Layouts as data
and the view switch come from a design study of one question page shown three
ways.

## What the frame offers

`AppFrame` (`template/ui/src/components/frame.tsx`) takes the app's nav and
may add:

- **Nav groups.** `group: "Work"` on a nav item lists it under that label.
- **A scoped nav.** `scope: (route) => NavScope | null` on a nav item swaps the
  sidebar for one record's sections, with a link back out. In the template,
  `#runs/RUN-004` lists Summary, Submissions and Log under "All runs".
- **An aside.** `aside={{ label, icon, render, summary }}` is a column on the
  right that stays across screens and can be hidden (remembered per admin).
  Under 768 px it is a bar along the bottom that opens a sheet. The template
  streams an activity journal into it.
- **A status line.** `liveNote={…}` replaces the line above each screen;
  omitted, it says how often reads check for updates; `false` hides it.
- **The rest of the header and column.** `actor` (a node, or `false` for no
  session call; by default the session's `display_name`, else its actor),
  `headerEnd` (a search box or data stamp), `contentClassName`,
  `sidebarWidth`, and `parent` on a hidden nav item for its crumb. One screen
  that throws shows an error in place of that screen, not a blank frame.

## Live updates

Reads poll every 15 seconds with ETags, which is the correctness path. For
speed, an admin may also open one event stream per tab (`useStream` in
`transport.ts`, `@admin.stream` with `Event` ids on the server): it reconnects
with backoff, resumes from the last id, and each event can refetch just the
reads it affects with `invalidate("/api/prefix")`. A command that saves
nothing a screen shows passes `{ invalidate: false }`.

## Alternate and generated layouts

A screen names its parts once and arranges them with a layout: rows, columns
and part names, as data (`template/ui/src/screens/overview.layouts.json`).
`parseLayouts` rejects a layout that names a part or grid the screen does not
have, so a layout written by a model can only rearrange what exists. The view
switch offers the layouts, remembers the choice and keeps it in the address.

## Adoption so far

Five existing admins have taken the shared parts on branches, each compared
screen by screen before and after; a sixth, a single very large file, has not
been started. Three server-rendered tools have also been rebuilt on the
template beside their old pages. The detailed records are kept privately.

An adopting app should pin, with `registerStates`, any state word it already
shows that the shared defaults style differently.

Still not covered by the shared parts: a read-only transport with no session
and no polling, and a phone-first header with global search.

## Not done yet

- The registry is not served anywhere, so `shadcn add @wheelhouse/...` does not
  work; shadcn resolves namespaced registries over HTTP only. `wheelhouse
  sync` copies the same files from disk in the meantime.
- The package is not on PyPI; depend on it by git URL (above) or a relative path.
- No charts, sparkline, log-stream screen, command palette, stacked meter,
  toast, link-based segmented filter or live pause control in the template yet.
- Commands are JSON only, up to 1 MB: no file upload.
- `useStream` has no automated test (the template has no browser test
  runner); it was checked by hand in a browser, including reconnection and
  resume.
- uvicorn waits for open event streams before it stops. The template's
  `dev.sh` passes `--timeout-graceful-shutdown 3`; a deployment that serves
  streams needs the same flag.
- The idempotency memory and any stream state are per process: run one worker.
