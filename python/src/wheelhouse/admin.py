"""The ``Admin`` object: identity, command guards, idempotency, ETags, SSE.

An app declares reads, commands and streams on one ``Admin`` and serves
``admin.asgi()``. Everything an ``Admin`` remembers (the idempotency store, its
routes) lives on the instance; nothing is shared between two of them.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect
import json
import logging
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Iterable, Sequence
from urllib.parse import urlsplit

import anyio
from starlette.applications import Starlette
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.requests import ClientDisconnect, Request
from starlette.responses import FileResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from . import idempotency
from .errors import AdminError, Conflict, Invalid, NotFound
from .identity import Identity, ProxyHeaders

log = logging.getLogger("wheelhouse")

DEV_ACTOR = "human:dev"
NETWORK_ACTOR = "network:unidentified"
NETWORK_GROUP = "network"
MAX_BODY_BYTES = 1024 * 1024
MAX_KEY_LENGTH = 200
KEEPALIVE_SECONDS = 20.0  # under the common 30 to 60 second proxy idle timeouts

_APP_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_COMMAND_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")  # secrets.token_urlsafe(32)
_RESERVED = ("/session", "/commands")
_PUBLIC_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
_IDENTITY = "wheelhouse.identity"  # where the gate leaves the request's Identity in the ASGI scope
_LINE_BREAK = re.compile(r"\r\n|\r|\n")
_ETAG_RE = re.compile(r'^(W/)?"[\x21\x23-\x7e]*"$')


@dataclass(frozen=True)
class Context:
    """What a handler is told about the request."""

    actor: str
    groups: frozenset[str]
    query: dict[str, str]
    path_params: dict[str, Any]
    request: Request  # the Starlette request, for anything not covered above
    # The id a reconnecting stream resumes after: the ``Last-Event-ID`` header,
    # or ``?after=`` when there is no header. ``None`` on a first connection.
    last_event_id: str | None = None
    # A name to show for the actor, when the identity provider knows one.
    display_name: str | None = None


@dataclass(frozen=True)
class Event:
    """One server-sent event with an id and a name, for a stream handler to yield.

    ``data`` that is not a string is sent as JSON. ``id`` is what the browser
    sends back as ``Last-Event-ID`` when it reconnects; ``event`` is the name a
    client listens for (``EventSource.addEventListener(name)``); without one the
    event is a plain ``message``.
    """

    data: Any
    id: str | int | None = None
    event: str | None = None


@dataclass(frozen=True)
class Cached:
    """A read's answer already serialised: ``body`` is sent as it is.

    ``etag`` is the validator for those bytes (quoted or not; ``W/`` for a weak
    one). Without it the bytes are hashed, which still saves serialising.
    """

    body: bytes
    etag: str | None = None
    media_type: str = "application/json"


def _etag(value: Any) -> str | None:
    """An app-supplied validator as a header value: quoted, printable, no inner quote."""
    if value is None:
        return None
    tag = str(value)
    if not (tag.startswith('"') or tag.startswith('W/"')):
        tag = f'"{tag}"'
    if not _ETAG_RE.match(tag):
        raise ValueError(f"not a usable ETag: {value!r}")
    return tag


def _hash_etag(body: bytes) -> str:
    return '"' + hashlib.sha256(body).hexdigest()[:32] + '"'


def _dumps(payload: Any) -> bytes:
    return json.dumps(payload, default=str, separators=(",", ":"), ensure_ascii=False).encode()


def _json(body: bytes, status: int = 200, headers: dict[str, str] | None = None) -> Response:
    return Response(body, status_code=status, media_type="application/json", headers=headers)


def _error(message: str, status: int, headers: dict[str, str] | None = None) -> Response:
    return _json(_dumps({"error": message}), status, headers)


def _etag_matches(header: str | None, etag: str) -> bool:
    """RFC 9110 weak comparison of an If-None-Match header against ``etag``."""
    if not header:
        return False
    for candidate in header.split(","):
        candidate = candidate.strip()
        if candidate == "*" or candidate.removeprefix("W/") == etag.removeprefix("W/"):
            return True
    return False


async def _call(handler: Callable[..., Any], *args: Any) -> Any:
    if inspect.iscoroutinefunction(handler):
        return await handler(*args)
    result = await run_in_threadpool(handler, *args)
    if inspect.isawaitable(result):
        result = await result
    return result


def page(items: Iterable[Any], ctx: Context, *, default_limit: int = 50, max_limit: int = 200) -> dict[str, Any]:
    """Slice ``items`` by ``?limit=&offset=``.

    ``limit`` is clamped to ``1..max_limit`` and ``offset`` to ``>= 0``; the
    returned ``limit`` and ``offset`` are the values actually used. A value that
    is not an integer is a 422.
    """

    def number(name: str, default: int) -> int:
        raw = ctx.query.get(name, "")
        if raw == "":
            return default
        try:
            return int(raw)
        except ValueError:
            raise Invalid(f"{name} must be an integer") from None

    limit = max(1, min(number("limit", default_limit), max_limit))
    offset = max(0, number("offset", 0))
    rows = items if isinstance(items, Sequence) else list(items)
    return {"items": list(rows[offset:offset + limit]), "total": len(rows), "limit": limit, "offset": offset}


class _Gate:
    """Pure ASGI middleware: the identity check in front of every route except
    ``/healthz`` and the declared public routes, and the response headers every
    answer carries, public or not."""

    def __init__(self, app: ASGIApp, admin: "Admin") -> None:
        self.app = app
        self.admin = admin

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Any) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "private, no-store"
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "same-origin"
                headers["X-Frame-Options"] = "DENY"
            await send(message)

        path = scope["path"]
        root = scope.get("root_path", "")
        if root and path.startswith(root):
            path = path[len(root):]
        if path != "/healthz" and (scope.get("method", "GET"), path) not in self.admin._public:
            try:
                identity = await self.admin._resolve(Request(scope))
                denied = self.admin._refuse(identity)
            except AdminError as exc:
                denied = _error(exc.message, exc.status)
            except Exception:
                log.exception("%s admin: the identity provider failed", self.admin.app)
                denied = _error("Internal error", 500)
            if denied is not None:
                await denied(scope, receive, send_with_headers)
                return
            scope[_IDENTITY] = identity
        await self.app(scope, receive, send_with_headers)


class Admin:
    """One admin API.

    ``app``             short name, e.g. ``"ledger"``. Fixes the ``X-Requested-With``
                        value (``<app>-admin``), the CSRF cookie (``<app>_csrf``) and
                        the mode variable (``<APP>_ADMIN_MODE``).
    ``web_dir``         directory holding the built ``index.html``.
    ``allowed_groups``  Authentik groups that may use the API at all.
    ``command_groups``  groups that may issue commands; defaults to ``allowed_groups``.
    ``auth``            ``"authentik"`` (default) reads the sign-in proxy's headers.
                        ``"network"`` checks no identity: use it only for a listener
                        bound to a private network. Commands still need the
                        same-origin check, CSRF token and idempotency key. With
                        ``identify``, a short label for the provider, reported by
                        ``/api/session`` (default: the provider's ``auth``
                        attribute, else ``"custom"``).
    ``identify``        an identity provider, ``(request) -> Identity | None``, sync
                        or async. Default: the sign-in proxy's uid and groups
                        headers. It decides who is asking; ``allowed_groups``,
                        ``command_groups`` and the command guard apply as always.
    ``dev``             ``True`` for development mode, ``False`` to forbid it,
                        ``None`` (default) to read ``<APP>_ADMIN_MODE``.
    ``origins``         extra exact origins commands are accepted from, for a proxy
                        that rewrites ``Host``. An ``Origin`` whose host equals the
                        request's ``Host`` is always accepted.
    """

    AdminError = AdminError
    NotFound = NotFound
    Conflict = Conflict
    Invalid = Invalid
    Event = Event
    Cached = Cached
    page = staticmethod(page)

    def __init__(
        self,
        app: str,
        *,
        web_dir: str | os.PathLike[str] | None = None,
        allowed_groups: Iterable[str] = (),
        command_groups: Iterable[str] | None = None,
        auth: str | None = None,
        dev: bool | None = None,
        origins: Iterable[str] | None = None,
        identify: Callable[[Request], Any] | None = None,
    ) -> None:
        if not _APP_RE.match(app):
            raise ValueError("app must be a short lowercase name such as 'ledger' or 'field-kit'")
        if isinstance(allowed_groups, str) or isinstance(command_groups, str):
            raise TypeError("groups must be a collection of names, not a string")
        self.app = app
        self.web_dir = Path(web_dir) if web_dir is not None else None
        if identify is None:
            auth = "authentik" if auth is None else auth
            if auth not in ("authentik", "network"):
                raise ValueError("auth must be 'authentik' or 'network'")
            self._provider: Callable[[Request], Any] | None = ProxyHeaders() if auth == "authentik" else None
        else:
            if not callable(identify):
                raise TypeError("identify must be a callable taking the request")
            if auth == "network":
                raise ValueError("network auth checks no identity, so it takes no identify provider")
            auth = getattr(identify, "auth", "custom") if auth is None else auth
            if not isinstance(auth, str) or not _APP_RE.match(auth):
                raise ValueError("auth must be a short lowercase label such as 'links'")
            self._provider = identify
        self.auth = auth
        self.allowed_groups = frozenset(allowed_groups)
        if auth == "network":
            # No identity check: the network boundary (a tailnet-only listener) is the
            # control. Every caller holds one fixed group so the rest of the guard is uniform.
            if self.allowed_groups or command_groups is not None:
                raise ValueError("network auth takes no groups; everyone who can reach the listener is allowed")
            self.allowed_groups = frozenset({NETWORK_GROUP})
        if not self.allowed_groups:
            raise ValueError("allowed_groups must name at least one group")
        self.command_groups = self.allowed_groups if command_groups is None else frozenset(command_groups)
        if not self.command_groups <= self.allowed_groups:
            raise ValueError("command_groups must be a subset of allowed_groups")
        self.mode_env = re.sub(r"[^A-Z0-9]", "_", app.upper()) + "_ADMIN_MODE"
        self.dev = self._resolve_dev(dev)
        self.requested_with = f"{app}-admin"
        self.csrf_cookie = app.replace("-", "_") + "_csrf"
        self._origins = None if origins is None else frozenset(o.rstrip("/").lower() for o in origins)
        self._idempotency = idempotency.IdempotencyStore()
        self._routes: list[Route] = []
        self._paths: set[tuple[str, str]] = set()
        self._public: set[tuple[str, str]] = set()
        self._startup: list[Callable[[], Any]] = []
        self._shutdown: list[Callable[[], Any]] = []
        if self.dev:
            log.warning(
                "%s admin is in development mode: every request is %s with full access. "
                "Never expose this beyond localhost.", app, DEV_ACTOR,
            )

    def _resolve_dev(self, dev: bool | None) -> bool:
        if dev is not None:
            return bool(dev)
        value = os.environ.get(self.mode_env, "").strip().lower()
        if value == "dev":
            return True
        if value in ("", "authentik", self.auth):
            return False
        raise ValueError(f"{self.mode_env} must be 'dev' or {self.auth!r} (or unset), not {value!r}")

    # --- identity ------------------------------------------------------------

    async def _resolve(self, request: Request) -> Identity | None:
        """Ask the provider who this is. Development mode and network mode answer
        without one, exactly as before the provider seam existed."""
        if self.dev:
            return Identity(DEV_ACTOR, self.allowed_groups)
        if self._provider is None:
            # Network mode. A Tailscale serve proxy names the user; a direct tailnet connection does not.
            login = request.headers.get("tailscale-user-login", "").strip()
            return Identity(f"tailscale:{login}" if login else NETWORK_ACTOR, self.allowed_groups)
        found = self._provider(request)
        if inspect.isawaitable(found):
            found = await found
        if found is not None and not isinstance(found, Identity):
            raise TypeError(f"identify must return an Identity or None, not {type(found).__name__}")
        return found

    def _refuse(self, identity: Identity | None) -> Response | None:
        if identity is None or not identity.actor:
            return _error("Sign-in required", 401)
        if not identity.groups & self.allowed_groups:
            return _error("Access denied", 403)
        return None

    def _context(self, request: Request) -> Context:
        identity = request.scope.get(_IDENTITY)
        if not isinstance(identity, Identity):  # _Gate has already refused the request otherwise
            raise RuntimeError("request reached a handler without passing the identity gate")
        resume = (request.headers.get("last-event-id", "").strip()
                  or request.query_params.get("after", "").strip() or None)
        return Context(identity.actor, identity.groups, dict(request.query_params), dict(request.path_params),
                       request, resume, identity.display_name)

    # --- registration --------------------------------------------------------

    def _add(self, path: str, endpoint: Callable[..., Any], method: str) -> None:
        if (method, path) in self._paths:
            raise ValueError(f"{method} {path} is already registered")
        self._paths.add((method, path))
        self._routes.append(Route(path, self._safely(endpoint), methods=[method]))

    def _api_path(self, path: str) -> str:
        if not path.startswith("/") or path == "/":
            raise ValueError("path must start with '/' and name a resource, e.g. '/runs'")
        if any(path == r or path.startswith(r + "/") for r in _RESERVED):
            raise ValueError(f"{path} is reserved by wheelhouse")
        return "/api" + path

    def public(self, path: str, *, methods: Iterable[str] = ("GET",)) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """A route outside the identity gate, for an identity provider's own
        endpoints such as a sign-in link exchange. The handler takes the Starlette
        ``request`` and returns a ``Response`` or JSON-able data.

        Only the exact path and the named methods are public. The answer still
        carries the security headers and the error shape. It gets no identity,
        no CSRF check and no idempotency: it must be safe to call by anyone who
        can reach the server.
        """
        if not isinstance(path, str) or not path.startswith("/") or path == "/" or "{" in path:
            raise ValueError("a public path must be an exact path such as '/sign-in', with no parameters")
        if path in ("/healthz", "/api", "/api/session", "/api/commands") or path.startswith("/api/commands/"):
            raise ValueError(f"{path} cannot be public")
        verbs = tuple(dict.fromkeys(m.upper() for m in methods))
        if not verbs or not set(verbs) <= _PUBLIC_METHODS:
            raise ValueError(f"methods must be some of {sorted(_PUBLIC_METHODS)}")
        if any((verb, path) in self._paths for verb in verbs):
            raise ValueError(f"{path} is already registered")

        def register(handler: Callable[..., Any]) -> Callable[..., Any]:
            async def endpoint(request: Request) -> Response:
                result = await _call(handler, request)
                return result if isinstance(result, Response) else _json(_dumps(result))

            for verb in verbs:
                self._add(path, endpoint, verb)
                self._public.add((verb, path))
                if verb == "GET":
                    self._public.add(("HEAD", path))
            return handler

        return register

    def read(
        self, path: str, *, etag: Callable[[Context], Any] | None = None
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """``GET /api<path>``. The handler takes ``ctx`` and returns JSON-able data,
        a ``Cached`` (bytes already serialised, with or without their ETag), or a
        Starlette ``Response`` to bypass JSON and the ETag.

        ``etag``, if given, is called with ``ctx`` before the handler (sync or
        async) and returns the current validator, or ``None`` when it cannot
        tell. A matching ``If-None-Match`` is answered ``304`` without calling
        the handler. It must change whenever the body would.
        """

        def register(handler: Callable[..., Any]) -> Callable[..., Any]:
            async def endpoint(request: Request) -> Response:
                ctx = self._context(request)
                asked = request.headers.get("if-none-match")
                known = _etag(await _call(etag, ctx)) if etag is not None else None
                if known is not None and _etag_matches(asked, known):
                    return Response(status_code=304, headers={"ETag": known})
                result = await _call(handler, ctx)
                if isinstance(result, Response):
                    return result
                media = "application/json"
                if isinstance(result, Cached):
                    if not isinstance(result.body, (bytes, bytearray, memoryview)):
                        raise TypeError("Cached.body must be bytes")
                    body, media = bytes(result.body), result.media_type
                    tag = _etag(result.etag) or known or _hash_etag(body)
                else:
                    body = _dumps(result)
                    tag = known or _hash_etag(body)
                if _etag_matches(asked, tag):
                    return Response(status_code=304, headers={"ETag": tag})
                return Response(body, media_type=media, headers={"ETag": tag})

            self._add(self._api_path(path), endpoint, "GET")
            return handler

        return register

    def command(self, name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """``POST /api/commands/<name>``. The handler takes ``ctx, body``."""
        if not _COMMAND_RE.match(name):
            raise ValueError("command name must be lowercase letters, digits and hyphens")

        def register(handler: Callable[..., Any]) -> Callable[..., Any]:
            async def endpoint(request: Request) -> Response:
                ctx = self._context(request)
                refused = self._guard(request, ctx)
                if refused is not None:
                    return refused
                key = request.headers.get("idempotency-key", "").strip()
                if not key:
                    return _error("Idempotency-Key header required", 400)
                if len(key) > MAX_KEY_LENGTH:
                    return _error("Idempotency-Key is too long", 400)
                body = await self._body(request)
                fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
                claim = (ctx.actor, name, key)
                state, stored = self._idempotency.begin(claim, fingerprint)
                if state == idempotency.REPLAY and stored is not None:
                    return _json(stored[1], stored[0], {"Idempotent-Replay": "true"})
                if state == idempotency.BUSY:
                    return _error("A command with this Idempotency-Key is still running", 409)
                if state == idempotency.MISMATCH:
                    return _error("Idempotency-Key was already used with a different request", 422)
                try:
                    result = await _call(handler, ctx, body)
                    payload = _dumps(result)
                except BaseException:
                    self._idempotency.abandon(claim)
                    raise
                self._idempotency.finish(claim, 200, payload)
                return _json(payload)

            self._add(f"/api/commands/{name}", endpoint, "POST")
            return handler

        return register

    def stream(self, path: str, *, keepalive: float | None = KEEPALIVE_SECONDS) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """``GET /api<path>`` as server-sent events. The handler takes ``ctx`` and
        returns (or is) a sync or async generator. Each item is one event: a
        string (data only, as before), an ``Event``, or a tuple ``(id, data)`` or
        ``(id, event, data)``.

        ``keepalive`` is the seconds of quiet after which a comment line is sent
        so a proxy does not close an idle stream; ``None`` or ``0`` turns it off.
        When the client goes away the handler is cancelled and closed at once.
        """
        if keepalive is not None and (isinstance(keepalive, bool) or keepalive < 0):
            raise ValueError("keepalive must be a number of seconds, or None for none")
        interval = float(keepalive) if keepalive else None

        def register(handler: Callable[..., Any]) -> Callable[..., Any]:
            async def endpoint(request: Request) -> Response:
                ctx = self._context(request)
                if inspect.isasyncgenfunction(handler) or inspect.isgeneratorfunction(handler):
                    source = handler(ctx)
                else:
                    source = await _call(handler, ctx)
                if not hasattr(source, "__aiter__"):
                    source = iterate_in_threadpool(iter(source))
                return _EventStream(source, interval)

            self._add(self._api_path(path), endpoint, "GET")
            return handler

        return register

    # --- lifespan ------------------------------------------------------------

    def on_startup(self, hook: Callable[[], Any]) -> Callable[[], Any]:
        """Run ``hook()`` (sync or async) when the server starts, in the order
        registered. If one raises, the server does not start."""
        self._startup.append(hook)
        return hook

    def on_shutdown(self, hook: Callable[[], Any]) -> Callable[[], Any]:
        """Run ``hook()`` (sync or async) when the server stops, in the reverse
        order of registration. A failing hook is logged and the rest still run."""
        self._shutdown.append(hook)
        return hook

    @contextlib.asynccontextmanager
    async def lifespan(self, app: Any = None) -> AsyncIterator[None]:
        """The startup and shutdown hooks as an ASGI lifespan. ``asgi()`` wires it
        in; a parent app that mounts this one passes ``lifespan=admin.lifespan``,
        because a mounted app's lifespan is not run."""
        for hook in list(self._startup):
            await _call(hook)
        try:
            yield
        finally:
            for hook in reversed(list(self._shutdown)):
                try:
                    await _call(hook)
                except Exception:
                    log.exception("%s admin: a shutdown hook failed", self.app)

    # --- command guard -------------------------------------------------------

    def _guard(self, request: Request, ctx: Context) -> Response | None:
        if not ctx.groups & self.command_groups:
            return _error("Your groups may not issue commands", 403)
        if request.headers.get("x-requested-with") != self.requested_with:
            return _error(f"X-Requested-With: {self.requested_with} header required", 403)
        if not self._same_origin(request):
            return _error("Cross-origin command denied", 403)
        token = request.cookies.get(self.csrf_cookie, "")
        supplied = request.headers.get("x-csrf-token", "")
        if not token or not supplied or not secrets.compare_digest(token.encode(), supplied.encode()):
            return _error("CSRF check failed", 403)
        return None

    def _same_origin(self, request: Request) -> bool:
        if request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
            return False
        origin = request.headers.get("origin")
        if origin is None:
            # Not a browser request: browsers send Origin on every POST. The
            # exact X-Requested-With value and the CSRF token still apply.
            return True
        origin = origin.rstrip("/").lower()
        if self._origins is not None and origin in self._origins:
            return True
        parts = urlsplit(origin)
        return parts.scheme in ("http", "https") and parts.netloc == request.headers.get("host", "").lower()

    async def _body(self, request: Request) -> dict[str, Any]:
        raw = b""
        try:
            async for chunk in request.stream():
                raw += chunk
                if len(raw) > MAX_BODY_BYTES:
                    raise AdminError("Command body is too large", 413)
        except ClientDisconnect:
            raise AdminError("Request body was not received", 400) from None
        if not raw.strip():
            return {}
        try:
            body = json.loads(raw)
        except (ValueError, RecursionError):
            raise AdminError("Command body is not valid JSON", 400) from None
        if not isinstance(body, dict):
            raise Invalid("Command body must be a JSON object")
        return body

    # --- built-in routes -----------------------------------------------------

    async def _healthz(self, request: Request) -> Response:
        return _json(_dumps({"ok": True}))

    async def _session(self, request: Request) -> Response:
        ctx = self._context(request)
        token = request.cookies.get(self.csrf_cookie, "")
        if not _TOKEN_RE.match(token):
            token = secrets.token_urlsafe(32)
        session: dict[str, Any] = {
            "actor": ctx.actor,
            "groups": sorted(ctx.groups),
            "csrf": token,
            "app": self.app,
            "auth": "dev" if self.dev else self.auth,
            # Lets the UI hide verbs the actor cannot use; the command guard still decides.
            "can_command": bool(ctx.groups & self.command_groups),
        }
        if ctx.display_name:
            session["display_name"] = ctx.display_name
        response = _json(_dumps(session))
        response.set_cookie(
            self.csrf_cookie, token, secure=not self.dev and self.auth != "network", httponly=True, samesite="strict",
            path=request.scope.get("root_path") or "/",
        )
        return response

    async def _index(self, request: Request) -> Response:
        index = self.web_dir / "index.html" if self.web_dir is not None else None
        if index is None or not index.is_file():
            return _error("Admin UI is not built: index.html is missing from the web directory", 503)
        return FileResponse(index, media_type="text/html")

    # --- errors and assembly -------------------------------------------------

    def _safely(self, endpoint: Callable[[Request], Any]) -> Callable[[Request], Any]:
        """Turn anything an endpoint raises into ``{"error": ...}``."""

        async def wrapped(request: Request) -> Response:
            try:
                return await endpoint(request)
            except AdminError as exc:
                return _error(exc.message, exc.status)
            except HTTPException:
                raise
            except Exception:
                log.exception("%s admin: %s %s failed", self.app, request.method, request.url.path)
                return _error("Internal error", 500)

        return wrapped

    def asgi(self) -> ASGIApp:
        """The ASGI app. Call it after every handler is registered."""

        async def http_error(request: Request, exc: Exception) -> Response:
            assert isinstance(exc, HTTPException)
            message = {404: "Not found", 405: "Method not allowed"}.get(exc.status_code, str(exc.detail))
            return _error(message, exc.status_code, dict(exc.headers or {}))

        async def unexpected(request: Request, exc: Exception) -> Response:
            log.error("%s admin: unhandled error", self.app, exc_info=exc)
            return _error("Internal error", 500)

        routes = [
            Route("/healthz", self._healthz, methods=["GET"]),
            Route("/api/session", self._safely(self._session), methods=["GET"]),
            *self._routes,
            Route("/", self._safely(self._index), methods=["GET"]),
        ]
        inner = Starlette(
            routes=routes, exception_handlers={HTTPException: http_error, Exception: unexpected}, lifespan=self.lifespan,
        )
        return _Gate(inner, self)


def _frame(item: Any) -> bytes:
    """One SSE event. A bare value is data only, as it always was."""
    if isinstance(item, tuple) and len(item) in (2, 3):
        item = Event(item[-1], id=item[0], event=item[1] if len(item) == 3 else None)
    if not isinstance(item, Event):
        lines = str(item).splitlines() or [""]
        return ("".join(f"data: {line}\n" for line in lines) + "\n").encode()
    head = ""
    if item.event is not None:
        name = str(item.event)
        if not name or _LINE_BREAK.search(name):
            raise ValueError("an event name must be non-empty and on one line")
        head += f"event: {name}\n"
    if item.id is not None:
        ident = str(item.id)
        if _LINE_BREAK.search(ident) or "\0" in ident:
            raise ValueError("an event id must be on one line and contain no NUL")
        head += f"id: {ident}\n"
    data = item.data if isinstance(item.data, str) else _dumps(item.data).decode()
    return (head + "".join(f"data: {line}\n" for line in _LINE_BREAK.split(data)) + "\n").encode()


async def _events(source: Any, keepalive: float | None) -> AsyncIterator[bytes]:
    """Frame each item from ``source``, with a comment line after each quiet
    ``keepalive`` seconds. Closing this generator cancels and closes ``source``."""
    yield b": open\n\n"  # flush headers so the client connects before the first line
    items = source.__aiter__()
    pending: asyncio.Future[Any] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(items.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=keepalive)
            if not done:
                yield b": keep-alive\n\n"
                continue
            finished, pending = pending, None
            try:
                item = finished.result()
            except StopAsyncIteration:
                break
            yield _frame(item)
    except Exception:
        log.exception("wheelhouse: stream failed")
        yield b"event: error\ndata: Stream failed\n\n"
    finally:
        # Shielded: the surrounding scope may already be cancelled (client gone).
        with anyio.CancelScope(shield=True), anyio.move_on_after(5):
            if pending is not None:
                pending.cancel()
                try:
                    await pending
                except BaseException:  # noqa: BLE001 - the handler's own ending
                    pass
            close = getattr(items, "aclose", None)
            if close is not None:
                try:
                    await close()
                except Exception:  # noqa: BLE001
                    log.exception("wheelhouse: closing a stream handler failed")


class _EventStream(Response):
    """A ``text/event-stream`` answer that stops, and closes its handler, as
    soon as the client disconnects, whatever ASGI version the server speaks."""

    media_type = "text/event-stream"

    def __init__(self, source: Any, keepalive: float | None) -> None:
        self.source = source
        self.keepalive = keepalive
        self.status_code = 200
        self.background = None
        self.init_headers({"X-Accel-Buffering": "no"})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async with anyio.create_task_group() as group:

            async def pump() -> None:
                frames = _events(self.source, self.keepalive)
                try:
                    await send({"type": "http.response.start", "status": self.status_code, "headers": self.raw_headers})
                    async for chunk in frames:
                        await send({"type": "http.response.body", "body": chunk, "more_body": True})
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
                except OSError:
                    pass  # the client went away mid-write
                finally:
                    with anyio.CancelScope(shield=True):
                        await frames.aclose()
                    group.cancel_scope.cancel()

            async def watch() -> None:
                while (await receive())["type"] != "http.disconnect":
                    pass
                group.cancel_scope.cancel()

            group.start_soon(pump)
            group.start_soon(watch)
