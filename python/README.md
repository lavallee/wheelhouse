# wheelhouse (Python)

The backend half of the shared admin-tool template. It replaces the guard code
each admin app used to copy: identity (from the sign-in proxy's headers, or a
provider the app supplies), the command
guards (same-origin, CSRF, idempotency), ETags on reads, a uniform error body,
pagination, and server-sent events. It is built on Starlette alone, so the
result mounts inside a Starlette or FastAPI app or runs by itself under uvicorn.

It is not published to PyPI. Depend on it by git URL, pinned to a tag:

```toml
[tool.uv.sources]
wheelhouse = { git = "https://github.com/lavallee/wheelhouse", subdirectory = "python", rev = "v0.1.0" }
```

## Example

```python
from pathlib import Path
from wheelhouse import Admin

admin = Admin(app="ledger", web_dir=Path("web"), allowed_groups={"admins"})
RUNS = {"2026-11-23": {"jobs": 4}}

@admin.read("/runs")
def runs(ctx):                       # ctx.actor, ctx.groups, ctx.query, ctx.path_params
    return admin.page(sorted(RUNS), ctx)

@admin.read("/runs/{run_id}")
def run(ctx):
    if ctx.path_params["run_id"] not in RUNS:
        raise admin.NotFound("No run with that id")
    return RUNS[ctx.path_params["run_id"]]

@admin.command("decide")
async def decide(ctx, body):         # sync or async; guards and idempotency already done
    return {"ok": True, "by": ctx.actor}

@admin.stream("/logs/{run_id}")
async def logs(ctx):                 # each yielded string, or admin.Event, is one event
    yield "started"

app = admin.asgi()                   # uvicorn module:app
```

Call `admin.asgi()` after every handler is registered. Paths given to `read`
and `stream` are served under `/api`; `command("decide")` is served at
`POST /api/commands/decide`.

## Wire contract

- `GET /healthz` returns `{"ok": true}` with no identity check.
- `GET /api/session` returns `{"actor", "groups", "csrf", "app", "auth", "can_command"}`,
  and `"display_name"` too when the identity provider knows one (it is absent
  otherwise, never `null`). `groups` is a sorted list and `auth` is
  `"authentik"`, `"network"`, `"dev"`, or the label of a custom provider. The CSRF
  token is in the body and in the cookie `<app>_csrf` (HttpOnly, SameSite=Strict,
  Secure outside development mode). A later call returns the same token.
- Reads, `GET /api/...`, return JSON with an `ETag` that is a hash of the body,
  unless the read supplies its own (see below). A matching `If-None-Match`
  (weak comparison, lists and `*` allowed) gets `304`.
- Commands, `POST /api/commands/<name>`, take a JSON object and require:
  - `X-Requested-With: <app>-admin`, exactly;
  - a same-origin request: an `Origin` header, when sent, must name the request's
    `Host` (or be one of `origins=`), and `Sec-Fetch-Site`, when sent, must be
    `same-origin`;
  - `X-CSRF-Token` equal to the session's token;
  - `Idempotency-Key`.

  The first three fail with `403`, a missing key with `400`.
- A repeated `Idempotency-Key` returns the first stored result without running
  the handler again, with the header `Idempotent-Replay: true`. Results are
  remembered for 24 hours, in the process, per actor and command. Only
  successes are remembered, so a failed command can be retried with the same
  key. A repeat that arrives while the first is still running gets `409`; a
  repeat with a different body gets `422`.
- Errors are always `{"error": "<message>"}`, including 401, 403, 404, 405, 422
  and 500. A handler exception is logged to the `wheelhouse` logger and answered
  with `{"error": "Internal error"}`.
- Every response carries `Cache-Control: private, no-store`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin` and
  `X-Frame-Options: DENY`.
- `GET /` serves `<web_dir>/index.html`. If it is missing the answer is a `503`
  JSON error saying the UI is not built.

## Identity

Outside development mode, every route except `/healthz` and the declared
public routes asks an identity provider who is calling. No identity is `401`.
No group in `allowed_groups` is `403`. `command_groups=`, if given, narrows who
may issue commands; it defaults to `allowed_groups`.

The default provider reads the sign-in proxy's `x-authentik-uid` and
`x-authentik-groups` (pipe-separated) headers, and no name. These headers are
trusted as sent. The app must be reachable only through the proxy, which must
strip any copy a client supplies.

Development mode is off unless `dev=True` is passed or the environment variable
`<APP>_ADMIN_MODE` is `dev` (`LEDGER_ADMIN_MODE`, `FIELD_KIT_ADMIN_MODE`). Any
value other than `dev`, `authentik`, the admin's `auth` label or empty is an
error at startup. In development mode every request is `human:dev` with all of
`allowed_groups`, identity headers are ignored and no provider is asked.
Commands still need their three headers.

### Identity providers

`Admin(app, identify=provider, auth="links", ...)` replaces the default.

- A provider is a callable `provider(request) -> Identity | None`, sync or
  async, given the Starlette request. A sync provider runs on the event loop,
  so one that reads a file or a database should be `async`.
- `Identity(actor, groups=(), display_name=None)`: `actor` is the attribution
  string (`human:ada`), `groups` a collection of names (a bare string is a
  `TypeError`), `display_name` what the interface shows. Surrounding spaces are
  trimmed; an empty actor counts as no identity.
- `None` is `401 {"error": "Sign-in required"}`. Raising
  `AdminError(message, status)` refuses with that message and status. Raising
  anything else, or returning anything other than an `Identity` or `None`, is
  logged and answered `500 {"error": "Internal error"}`.
- The provider is asked once per request. Handlers see the result as
  `ctx.actor`, `ctx.groups` and `ctx.display_name`.
- `auth` labels the provider in `/api/session` (lowercase letters, digits and
  hyphens). Without it the label is the provider's `auth` attribute, or
  `"custom"`. `auth="network"` takes no provider.
- `allowed_groups`, `command_groups` and the whole command guard (exact
  `X-Requested-With`, same origin, CSRF token, idempotency key) are the same
  under every provider.

`proxy_headers(uid="x-authentik-uid", groups="x-authentik-groups", name=None,
separator="|")` builds the proxy provider with other header names, for example
`identify=proxy_headers(name="x-authentik-name")` to show the proxy's display
name. It labels itself `authentik`. Any header it reads must be stripped from
client requests by the proxy.

### Public routes

A provider that signs people in itself needs an endpoint the identity gate
does not guard, such as one that exchanges a sign-in link for a cookie:

```python
@admin.public("/sign-in")                       # methods=("GET",) by default
def sign_in(request):                           # the Starlette request; no ctx
    person = people.redeem(request.query_params.get("link", ""))
    if person is None:
        raise admin.AdminError("That sign-in link is not valid", 401)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("desk_session", person.session, httponly=True, samesite="strict", secure=True)
    return response
```

- Only that exact path and the named methods are public (GET also allows
  HEAD). `/sign-in/`, `/sign-in/x` and other methods are still gated.
- `/healthz`, `/`, `/api`, `/api/session` and anything under `/api/commands`
  cannot be public, nor can a path with parameters.
- A public route's answers carry the same security headers and the
  `{"error": ...}` shape. It gets no identity, CSRF check or idempotency, so it
  must be safe for anyone who can reach the server to call.

## Handlers

- `ctx` has `actor`, `groups` (a frozenset), `display_name` (or `None`),
  `query` (a dict of strings), `path_params`, `request` (the Starlette
  request) and `last_event_id` (see event streams).
- Raise `admin.NotFound` (404), `admin.Conflict` (409), `admin.Invalid` (422)
  or `admin.AdminError(message, status)` to answer with an error.
- `admin.page(items, ctx, default_limit=50, max_limit=200)` reads
  `?limit=&offset=` and returns `{"items", "total", "limit", "offset"}`. Out of
  range values are clamped and the values used are returned; a value that is
  not an integer is a `422`.
- A read may return a Starlette `Response` to bypass JSON and the ETag, for a
  file download.
- A read that already holds its answer as bytes returns
  `admin.Cached(body, etag=None, media_type="application/json")`. The bytes
  are sent as they are; `etag` (quoted or bare, `W/` for weak) is the
  validator, and without one the bytes are hashed rather than re-serialised.
- `@admin.read(path, etag=fn)` calls `fn(ctx)` (sync or async) before the
  handler. When the request's `If-None-Match` matches what it returns, the
  answer is `304` and the handler is not called. `fn` may return `None` when it
  cannot tell, and then the handler's body decides. It must change whenever the
  body would, for instance a revision number bumped only when the bytes change.

  ```python
  @admin.read("/nb/{slug}/picture", etag=lambda ctx: hub(ctx).etag)
  def picture(ctx):
      h = hub(ctx)
      return admin.Cached(h.picture_bytes, etag=h.etag)
  ```

  An ETag with a quote, a space or a control character is a programming error
  and answers `500`.
- A stream handler written as a generator starts sending at once, and an
  exception inside it ends the stream with `event: error`. To answer `404`
  first, write a plain function that checks, raises, and then returns the
  iterator.

## Event streams

`@admin.stream(path, keepalive=20.0)` serves `GET /api<path>` as
`text/event-stream`.

- Each item the handler yields is one event. A string is data only, framed as
  it always was. `Event(data, id=None, event=None)` adds an `id:` and an
  `event:` line; `data` that is not a string is sent as compact JSON. A tuple
  `(id, data)` or `(id, event, data)` is the same as the `Event`. An id or
  name with a line break (or an id with NUL) ends the stream with
  `event: error`.
- `ctx.last_event_id` is the id to resume after: the `Last-Event-ID` header
  (which the browser sends on its own reconnects), or `?after=` when there is
  no header, or `None`. A handler that keeps a sequence-numbered journal sends
  what follows that id and then waits for more.
- The first bytes are the comment `: open`. After each `keepalive` seconds
  with nothing to send, the comment `: keep-alive` is sent so a proxy with an
  idle timeout does not close a quiet stream. `keepalive=None` turns it off.
- When the client disconnects, the handler is cancelled where it is waiting
  and closed, so its `finally` runs at once. A handler written as a plain
  (sync) iterator runs in a thread and cannot be interrupted mid-item.
- The browser's `EventSource` sends cookies but cannot send custom headers, so
  a stream is a read: it needs the identity the gate checks and nothing more.
  The template's `useStream` hook reconnects with backoff and resumes with
  `?after=<last id>`.

```python
JOURNAL: list[dict] = []          # appended to by commands

@admin.stream("/activity")
async def activity(ctx):
    seen = int(ctx.last_event_id or 0)
    while True:
        for n, row in enumerate(JOURNAL[seen:], start=seen + 1):
            yield admin.Event(row, id=n, event="activity")
        seen = len(JOURNAL)
        await asyncio.sleep(1)
```

## Startup and shutdown

`@admin.on_startup` and `@admin.on_shutdown` register functions (sync or
async, no arguments) run in the ASGI lifespan: startup hooks in the order
registered, shutdown hooks in reverse. A startup hook that raises stops the
server starting, which is the place to refuse a second worker; shutdown hooks
then do not run. A shutdown hook that raises is logged and the others still
run.

`asgi()` wires the hooks in. A parent app that mounts the admin must pass
`lifespan=admin.lifespan`, because Starlette does not run a mounted app's
lifespan.

## Limits

The idempotency memory is per process. It is lost on restart and not shared
between workers, so run one worker per app.

uvicorn waits for every open response before it stops, and an event stream
does not end on its own, so a stop with a browser tab open waits until the tab
closes. Pass `--timeout-graceful-shutdown N`: after N seconds uvicorn cancels
the streams, each handler's cleanup runs, and the process exits (uvicorn logs
each cancelled stream). The lifespan shutdown hooks run after that.

## Tests

```
uv sync --extra dev
uv run pytest -q
```

## Admins on a private network

Some admins are reachable only over a private network and have no sign-in
proxy. `Admin("bookmarks", auth="network")` checks no identity: every caller
is `network:unidentified`, or `tailscale:<login>` when a Tailscale proxy
supplies `tailscale-user-login`. Commands still need the same-origin check,
the CSRF token and an idempotency key. Use it only for a listener that is not
reachable from outside that network.
