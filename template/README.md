# Sample admin

An admin tool built from the Wheelhouse template.

| Path | What it is |
|---|---|
| `backend/app.py` | The API: one function per read and per command |
| `backend/sample.py` | In-memory sample data. Replace with the real store |
| `ui/src/main.tsx` | The nav (one line per screen, grouped by `group`), the status line and the aside |
| `ui/src/screens/activity.tsx` | The live activity journal: one event stream per tab, shown in the aside |
| `ui/src/screens/` | The screens |
| `ui/src/app.config.ts` | The admin's id, name and tagline |
| `web/index.html` | The built UI, one file, served by the backend |

```console
$ ./ci.sh     # install, test, build
$ ./dev.sh    # http://127.0.0.1:8870, development mode
```

Development mode is on only when `SAMPLE_ADMIN_MODE=dev`. Otherwise the admin
expects the sign-in proxy's `x-authentik-uid` and `x-authentik-groups` headers
and must be reachable only through that proxy, unless `backend/app.py` passes
its own `identify=` provider (see the wheelhouse package README). Change
`allowed_groups` to the groups your proxy sends.

Run one worker: the command replay memory is per process. The activity stream
stays open while a tab is, so run uvicorn with `--timeout-graceful-shutdown`
(as `dev.sh` does) or a stop waits for every tab to close.

To see whether the shared parts here have fallen behind the registry:

```console
$ wheelhouse drift ui
```
