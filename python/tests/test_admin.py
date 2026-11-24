from __future__ import annotations

import asyncio
import threading

import pytest
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from wheelhouse import Admin, AdminError, NotFound

OPERATOR = {"x-authentik-uid": "human:ada", "x-authentik-groups": "staff|admins"}


def build(tmp_path=None, **kwargs):
    """A small app that exercises every kind of route, plus a call log."""
    kwargs.setdefault("allowed_groups", {"admins"})
    admin = Admin("ledger", web_dir=tmp_path, **kwargs)
    calls: list[dict] = []
    state = {"runs": ["a", "b"]}

    @admin.read("/runs")
    def runs(ctx):
        return {"runs": state["runs"], "actor": ctx.actor, "q": ctx.query.get("q")}

    @admin.read("/runs/{run_id}")
    async def run(ctx):
        if ctx.path_params["run_id"] not in state["runs"]:
            raise admin.NotFound("No run with that id")
        return {"id": ctx.path_params["run_id"]}

    @admin.read("/rows")
    def rows(ctx):
        return admin.page(list(range(500)), ctx)

    @admin.read("/boom")
    def boom(ctx):
        raise RuntimeError("secret database password")

    @admin.command("decide")
    def decide(ctx, body):
        calls.append(body)
        return {"ok": True, "n": len(calls), "actor": ctx.actor}

    @admin.command("decide-async")
    async def decide_async(ctx, body):
        calls.append(body)
        return {"ok": True, "n": len(calls)}

    @admin.command("explode")
    def explode(ctx, body):
        calls.append(body)
        if body.get("how") == "invalid":
            raise admin.Invalid("id and answer required")
        raise RuntimeError("secret database password")

    @admin.stream("/logs/{id}")
    async def logs(ctx):
        yield f"start {ctx.path_params['id']}"
        yield "two\nlines"

    @admin.stream("/synclogs/{id}")
    def synclogs(ctx):
        if ctx.path_params["id"] == "missing":
            raise admin.NotFound("No such log")
        return iter(["one", "two"])

    return admin, calls, state


def client_for(admin, headers=OPERATOR):
    # https, because the CSRF cookie is Secure outside development mode.
    return TestClient(admin.asgi(), base_url="https://testserver", headers=headers or {})


def command_headers(client, **overrides):
    headers = {
        "X-Requested-With": "ledger-admin",
        "X-CSRF-Token": client.get("/api/session").json()["csrf"],
        "Idempotency-Key": "key-1",
    }
    headers.update(overrides)
    return {k: v for k, v in headers.items() if v is not None}


@pytest.fixture
def setup(tmp_path):
    admin, calls, state = build(tmp_path)
    return admin, client_for(admin), calls, state


# --- healthz, session, identity ----------------------------------------------

def test_healthz_needs_no_identity(setup):
    admin, _, _, _ = setup
    response = client_for(admin, headers=None).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_session_shape(setup):
    _, client, _, _ = setup
    response = client.get("/api/session")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"actor", "groups", "csrf", "app", "auth", "can_command"}
    assert body["can_command"] is True
    assert body["actor"] == "human:ada"
    assert body["groups"] == ["admins", "staff"]
    assert body["app"] == "ledger"
    assert body["auth"] == "authentik"
    assert response.cookies["ledger_csrf"] == body["csrf"]
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    assert response.headers["cache-control"] == "private, no-store"
    # A second call keeps the token, so two tabs do not invalidate each other.
    assert client.get("/api/session").json()["csrf"] == body["csrf"]


def test_session_does_not_adopt_a_planted_cookie(setup):
    _, client, _, _ = setup
    client.cookies.set("ledger_csrf", "attacker-chosen")
    assert client.get("/api/session").json()["csrf"] != "attacker-chosen"


def test_dev_mode_is_off_by_default(monkeypatch):
    monkeypatch.delenv("LEDGER_ADMIN_MODE", raising=False)
    admin, _, _ = build()
    assert admin.dev is False
    assert client_for(admin, headers=None).get("/api/session").status_code == 401


def test_dev_mode_by_env_var(monkeypatch):
    monkeypatch.setenv("LEDGER_ADMIN_MODE", "dev")
    admin, _, _ = build()
    assert admin.dev is True
    body = TestClient(admin.asgi()).get("/api/session").json()
    assert body["actor"] == "human:dev"
    assert body["auth"] == "dev"
    assert body["groups"] == ["admins"]


def test_dev_mode_env_var_is_per_app_and_strict(monkeypatch):
    monkeypatch.setenv("FIELD_KIT_ADMIN_MODE", "dev")
    monkeypatch.delenv("LEDGER_ADMIN_MODE", raising=False)
    assert Admin("field-kit", allowed_groups={"g"}).dev is True
    assert Admin("ledger", allowed_groups={"g"}).dev is False
    assert Admin("field-kit", allowed_groups={"g"}, dev=False).dev is False
    monkeypatch.setenv("LEDGER_ADMIN_MODE", "development")
    with pytest.raises(ValueError):
        Admin("ledger", allowed_groups={"g"})


def test_dev_mode_ignores_identity_headers():
    admin, _, _ = build(dev=True)
    client = TestClient(admin.asgi(), headers={"x-authentik-uid": "human:mallory"})
    assert client.get("/api/session").json()["actor"] == "human:dev"


def test_dev_mode_commands_still_need_the_guard():
    admin, calls, _ = build(dev=True)
    client = TestClient(admin.asgi())
    assert client.post("/api/commands/decide", json={}).status_code == 403
    assert client.post("/api/commands/decide", json={}, headers=command_headers(client)).status_code == 200
    assert len(calls) == 1


@pytest.mark.parametrize("path", ["/api/session", "/api/runs", "/api/nope", "/", "/api/logs/1"])
def test_no_identity_is_401(setup, path):
    admin, _, _, _ = setup
    response = client_for(admin, headers=None).get(path)
    assert response.status_code == 401
    assert set(response.json()) == {"error"}
    assert response.headers["cache-control"] == "private, no-store"


def test_identity_without_allowed_group_is_403(setup):
    admin, _, _, _ = setup
    for groups in ("", "staff|other", "admins-not"):
        client = client_for(admin, {"x-authentik-uid": "human:eve", "x-authentik-groups": groups})
        response = client.get("/api/runs")
        assert response.status_code == 403
        assert set(response.json()) == {"error"}


def test_groups_without_uid_is_401(setup):
    admin, _, _, _ = setup
    client = client_for(admin, {"x-authentik-groups": "admins"})
    assert client.get("/api/runs").status_code == 401


def test_command_without_identity_is_401(setup):
    admin, _, calls, _ = setup
    response = client_for(admin, headers=None).post("/api/commands/decide", json={})
    assert response.status_code == 401
    assert calls == []


def test_command_groups_narrow_who_may_write(tmp_path):
    admin, calls, _ = build(allowed_groups={"admins", "readers"}, command_groups={"admins"})
    reader = client_for(admin, {"x-authentik-uid": "human:rae", "x-authentik-groups": "readers"})
    assert reader.get("/api/runs").status_code == 200
    response = reader.post("/api/commands/decide", json={}, headers=command_headers(reader))
    assert response.status_code == 403
    assert calls == []
    with pytest.raises(ValueError):
        Admin("ledger", allowed_groups={"a"}, command_groups={"b"})


def test_constructor_refuses_unsafe_configuration():
    with pytest.raises(ValueError):
        Admin("ledger", allowed_groups=set())
    with pytest.raises(TypeError):
        Admin("ledger", allowed_groups="admins")
    with pytest.raises(ValueError):
        Admin("Ledger Admin", allowed_groups={"g"})


# --- reads ---------------------------------------------------------------------

def test_read_etag_then_304(setup):
    _, client, _, state = setup
    first = client.get("/api/runs?q=x")
    assert first.status_code == 200
    assert first.json() == {"runs": ["a", "b"], "actor": "human:ada", "q": "x"}
    assert first.headers["content-type"] == "application/json"
    assert first.headers["cache-control"] == "private, no-store"
    etag = first.headers["etag"]
    assert etag.startswith('"') and etag.endswith('"')

    again = client.get("/api/runs?q=x", headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.content == b""
    assert again.headers["etag"] == etag
    assert again.headers["cache-control"] == "private, no-store"

    # Weak validators and lists match too (a compressing proxy weakens ETags).
    assert client.get("/api/runs?q=x", headers={"If-None-Match": f'"zzz", W/{etag}'}).status_code == 304

    state["runs"] = ["a", "b", "c"]
    changed = client.get("/api/runs?q=x", headers={"If-None-Match": etag})
    assert changed.status_code == 200
    assert changed.headers["etag"] != etag


def test_async_read_and_path_params(setup):
    _, client, _, _ = setup
    assert client.get("/api/runs/a").json() == {"id": "a"}


# --- commands ------------------------------------------------------------------

@pytest.mark.parametrize("missing,status", [
    ("X-Requested-With", 403),
    ("X-CSRF-Token", 403),
    ("Idempotency-Key", 400),
])
def test_command_rejected_without_each_header(setup, missing, status):
    _, client, calls, _ = setup
    response = client.post("/api/commands/decide", json={"id": 1}, headers=command_headers(client, **{missing: None}))
    assert response.status_code == status
    assert set(response.json()) == {"error"}
    assert calls == []


def test_command_rejected_with_wrong_requested_with(setup):
    _, client, calls, _ = setup
    headers = command_headers(client, **{"X-Requested-With": "tally-admin"})
    assert client.post("/api/commands/decide", json={}, headers=headers).status_code == 403
    assert calls == []


def test_command_rejected_with_wrong_csrf_token(setup):
    _, client, calls, _ = setup
    headers = command_headers(client, **{"X-CSRF-Token": "not-the-token"})
    response = client.post("/api/commands/decide", json={}, headers=headers)
    assert response.status_code == 403
    assert response.json() == {"error": "CSRF check failed"}
    assert calls == []


def test_command_rejected_without_session_cookie(setup):
    admin, client, calls, _ = setup
    token = client.get("/api/session").json()["csrf"]
    fresh = client_for(admin)  # same identity, but never called /api/session
    headers = {"X-Requested-With": "ledger-admin", "X-CSRF-Token": token, "Idempotency-Key": "k"}
    assert fresh.post("/api/commands/decide", json={}, headers=headers).status_code == 403
    assert calls == []


@pytest.mark.parametrize("extra", [
    {"Origin": "https://evil.example"},
    {"Origin": "null"},
    {"Origin": "https://testserver.evil.example"},
    {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site", "Origin": "https://testserver"},
])
def test_command_rejected_cross_origin(setup, extra):
    _, client, calls, _ = setup
    response = client.post("/api/commands/decide", json={}, headers=command_headers(client, **extra))
    assert response.status_code == 403
    assert response.json() == {"error": "Cross-origin command denied"}
    assert calls == []


def test_command_accepted_with_all_headers(setup):
    _, client, calls, _ = setup
    headers = command_headers(client, Origin="https://testserver", **{"Sec-Fetch-Site": "same-origin"})
    response = client.post("/api/commands/decide", json={"id": 7}, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"ok": True, "n": 1, "actor": "human:ada"}
    assert calls == [{"id": 7}]


def test_configured_origins_are_accepted_alongside_the_host():
    admin, calls, _ = build(origins={"https://ledger.example/"})
    client = client_for(admin)
    ok = command_headers(client, Origin="https://ledger.example")
    assert client.post("/api/commands/decide", json={}, headers=ok).status_code == 200
    same = command_headers(client, Origin="https://testserver", **{"Idempotency-Key": "key-2"})
    assert client.post("/api/commands/decide", json={}, headers=same).status_code == 200
    bad = command_headers(client, Origin="https://elsewhere.example", **{"Idempotency-Key": "key-3"})
    assert client.post("/api/commands/decide", json={}, headers=bad).status_code == 403
    assert len(calls) == 2


def test_idempotent_replay_returns_first_result_without_rerunning(setup):
    _, client, calls, _ = setup
    headers = command_headers(client)
    first = client.post("/api/commands/decide", json={"id": 7}, headers=headers)
    second = client.post("/api/commands/decide", json={"id": 7}, headers=headers)
    assert first.status_code == second.status_code == 200
    assert second.json() == first.json() == {"ok": True, "n": 1, "actor": "human:ada"}
    assert second.headers["idempotent-replay"] == "true"
    assert len(calls) == 1

    other = client.post("/api/commands/decide", json={"id": 7}, headers={**headers, "Idempotency-Key": "key-2"})
    assert other.json()["n"] == 2


def test_idempotency_key_is_scoped_to_command_and_actor(setup):
    admin, client, calls, _ = setup
    headers = command_headers(client)
    client.post("/api/commands/decide", json={}, headers=headers)
    # Same key, different command: runs, does not return decide's result.
    assert client.post("/api/commands/decide-async", json={}, headers=headers).json() == {"ok": True, "n": 2}
    # Same key, different actor: runs.
    other = client_for(admin, {"x-authentik-uid": "human:bob", "x-authentik-groups": "admins"})
    response = other.post("/api/commands/decide", json={}, headers=command_headers(other))
    assert response.json()["actor"] == "human:bob"
    assert len(calls) == 3


def test_idempotency_key_reused_with_a_different_body_is_refused(setup):
    _, client, calls, _ = setup
    headers = command_headers(client)
    client.post("/api/commands/decide", json={"id": 7}, headers=headers)
    response = client.post("/api/commands/decide", json={"id": 8}, headers=headers)
    assert response.status_code == 422
    assert set(response.json()) == {"error"}
    assert len(calls) == 1


def test_failed_command_is_not_remembered(setup):
    _, client, calls, _ = setup
    headers = command_headers(client)
    for _ in range(2):
        response = client.post("/api/commands/explode", json={"how": "invalid"}, headers=headers)
        assert response.status_code == 422
        assert response.json() == {"error": "id and answer required"}
    assert len(calls) == 2


def test_idempotency_memory_expires_after_24h(setup):
    admin, client, calls, _ = setup
    clock = {"t": 1000.0}
    admin._idempotency._now = lambda: clock["t"]
    headers = command_headers(client)
    client.post("/api/commands/decide", json={}, headers=headers)
    clock["t"] += 24 * 3600 - 1
    client.post("/api/commands/decide", json={}, headers=headers)
    assert len(calls) == 1
    clock["t"] += 2
    client.post("/api/commands/decide", json={}, headers=headers)
    assert len(calls) == 2
    assert len(admin._idempotency) == 1


def test_concurrent_duplicate_runs_the_handler_once():
    admin = Admin("ledger", allowed_groups={"admins"})
    started, release, calls = threading.Event(), threading.Event(), []

    @admin.command("slow")
    def slow(ctx, body):
        calls.append(body)
        started.set()
        release.wait(5)
        return {"ok": True}

    client = client_for(admin)
    headers = command_headers(client)
    results = []
    twin = client_for(admin)  # a second connection holding the same session cookie
    twin.cookies.set("ledger_csrf", headers["X-CSRF-Token"])
    first = threading.Thread(
        target=lambda: results.append(twin.post("/api/commands/slow", json={}, headers=headers))
    )
    first.start()
    assert started.wait(5)
    duplicate = client.post("/api/commands/slow", json={}, headers=headers)
    release.set()
    first.join(5)
    assert duplicate.status_code == 409
    assert set(duplicate.json()) == {"error"}
    assert results[0].status_code == 200
    assert len(calls) == 1
    assert client.post("/api/commands/slow", json={}, headers=headers).json() == {"ok": True}
    assert len(calls) == 1


# --- error shape ---------------------------------------------------------------

def assert_error(response, status):
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"} and isinstance(body["error"], str) and body["error"]
    assert response.headers["content-type"] == "application/json"
    return body["error"]


def test_error_shape_404_unknown_route(setup):
    _, client, _, _ = setup
    assert_error(client.get("/api/nope"), 404)
    assert_error(client.get("/nope"), 404)
    assert_error(client.post("/api/commands/nope", json={}), 404)


def test_error_shape_404_from_handler(setup):
    _, client, _, _ = setup
    assert assert_error(client.get("/api/runs/zzz"), 404) == "No run with that id"


def test_error_shape_405(setup):
    _, client, _, _ = setup
    assert_error(client.post("/api/runs", json={}), 405)
    assert_error(client.get("/api/commands/decide"), 405)
    assert_error(client.delete("/api/session"), 405)


def test_error_shape_malformed_json(setup):
    _, client, calls, _ = setup
    headers = {**command_headers(client), "Content-Type": "application/json"}
    assert_error(client.post("/api/commands/decide", content=b"{not json", headers=headers), 400)
    assert_error(client.post("/api/commands/decide", content=b"[1, 2]", headers=headers), 422)
    assert calls == []


def test_error_shape_500_does_not_leak(setup, caplog):
    _, client, calls, _ = setup
    read = client.get("/api/boom")
    assert assert_error(read, 500) == "Internal error"
    assert "secret" not in read.text
    headers = command_headers(client)
    command = client.post("/api/commands/explode", json={}, headers=headers)
    assert assert_error(command, 500) == "Internal error"
    assert "secret" not in command.text
    # The traceback goes to the log, and the failed command may be retried.
    assert "secret database password" in caplog.text
    client.post("/api/commands/explode", json={}, headers=headers)
    assert len(calls) == 2


def test_admin_error_carries_a_custom_status():
    admin = Admin("ledger", allowed_groups={"admins"})

    @admin.read("/teapot")
    def teapot(ctx):
        raise AdminError("Short and stout", 418)

    response = client_for(admin).get("/api/teapot")
    assert response.status_code == 418
    assert response.json() == {"error": "Short and stout"}
    assert admin.NotFound is NotFound


# --- pagination ----------------------------------------------------------------

@pytest.mark.parametrize("query,limit,offset,first,count", [
    ("", 50, 0, 0, 50),
    ("?limit=10&offset=20", 10, 20, 20, 10),
    ("?limit=100000", 200, 0, 0, 200),
    ("?limit=0", 1, 0, 0, 1),
    ("?limit=-5&offset=-3", 1, 0, 0, 1),
    ("?offset=495", 50, 495, 495, 5),
    ("?offset=9999", 50, 9999, None, 0),
])
def test_pagination_bounds(setup, query, limit, offset, first, count):
    _, client, _, _ = setup
    body = client.get("/api/rows" + query).json()
    assert set(body) == {"items", "total", "limit", "offset"}
    assert (body["total"], body["limit"], body["offset"]) == (500, limit, offset)
    assert len(body["items"]) == count
    if count:
        assert body["items"][0] == first


def test_pagination_rejects_non_integers(setup):
    _, client, _, _ = setup
    assert assert_error(client.get("/api/rows?limit=ten"), 422) == "limit must be an integer"
    assert_error(client.get("/api/rows?offset=1.5"), 422)


# --- server-sent events --------------------------------------------------------

def events(text):
    return [block for block in text.split("\n\n") if block and not block.startswith(":")]


def test_sse_yields_events(setup):
    _, client, _, _ = setup
    response = client.get("/api/logs/42")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "private, no-store"
    assert events(response.text) == ["data: start 42", "data: two\ndata: lines"]


def test_sse_from_a_sync_iterator_and_404_before_streaming(setup):
    _, client, _, _ = setup
    assert events(client.get("/api/synclogs/1").text) == ["data: one", "data: two"]
    assert assert_error(client.get("/api/synclogs/missing"), 404) == "No such log"


def test_sse_is_guarded_by_identity(setup):
    admin, _, _, _ = setup
    assert client_for(admin, headers=None).get("/api/logs/42").status_code == 401
    wrong = client_for(admin, {"x-authentik-uid": "human:eve", "x-authentik-groups": "staff"})
    assert wrong.get("/api/logs/42").status_code == 403


def test_sse_failure_mid_stream_ends_with_an_error_event():
    admin = Admin("ledger", allowed_groups={"admins"})

    @admin.stream("/logs")
    async def logs(ctx):
        yield "one"
        await asyncio.sleep(0)
        raise RuntimeError("secret database password")

    text = client_for(admin).get("/api/logs").text
    assert events(text) == ["data: one", "event: error\ndata: Stream failed"]


# --- index.html ----------------------------------------------------------------

def test_index_served_when_built(setup, tmp_path):
    _, client, _, _ = setup
    (tmp_path / "index.html").write_text("<!doctype html><title>Ledger</title>")
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Ledger" in response.text
    assert response.headers["x-content-type-options"] == "nosniff"


def test_index_503_when_not_built(setup):
    _, client, _, _ = setup
    assert "not built" in assert_error(client.get("/"), 503)
    admin, _, _ = build()  # no web_dir at all
    assert_error(client_for(admin).get("/"), 503)


# --- isolation and mounting ----------------------------------------------------

def test_two_admins_are_isolated(tmp_path):
    ledger = Admin("ledger", allowed_groups={"ledger-admins"})
    tally = Admin("tally", allowed_groups={"tally-admins"}, dev=True)
    seen = {"ledger": 0, "tally": 0}

    @ledger.command("go")
    def ledger_go(ctx, body):
        seen["ledger"] += 1
        return {"app": "ledger"}

    @tally.command("go")
    def tally_go(ctx, body):
        seen["tally"] += 1
        return {"app": "tally"}

    @tally.read("/only-tally")
    def only_tally(ctx):
        return {}

    k = client_for(ledger, {"x-authentik-uid": "human:dev", "x-authentik-groups": "ledger-admins"})
    e = TestClient(tally.asgi())

    assert k.get("/api/session").json()["app"] == "ledger"
    assert e.get("/api/session").json()["app"] == "tally"
    assert ledger.dev is False and tally.dev is True
    assert k.get("/api/only-tally").status_code == 404
    # The other app's group does not open this one.
    outsider = client_for(ledger, {"x-authentik-uid": "human:x", "x-authentik-groups": "tally-admins"})
    assert outsider.get("/api/session").status_code == 403

    # Same actor, same command name, same key: each app runs its own handler.
    kh = {**command_headers(k), "Idempotency-Key": "shared"}
    eh = {"X-Requested-With": "tally-admin", "X-CSRF-Token": e.get("/api/session").json()["csrf"],
          "Idempotency-Key": "shared"}
    assert k.post("/api/commands/go", json={}, headers=kh).json() == {"app": "ledger"}
    assert e.post("/api/commands/go", json={}, headers=eh).json() == {"app": "tally"}
    assert seen == {"ledger": 1, "tally": 1}
    # Ledger's header value is not accepted by Tally.
    assert e.post("/api/commands/go", json={}, headers={**eh, "X-Requested-With": "ledger-admin"}).status_code == 403
    assert "ledger_csrf" in k.cookies and "tally_csrf" in e.cookies


def test_registration_mistakes_fail_at_import_time():
    admin = Admin("ledger", allowed_groups={"g"})
    admin.read("/runs")(lambda ctx: {})
    with pytest.raises(ValueError):
        admin.read("/runs")(lambda ctx: {})
    with pytest.raises(ValueError):
        admin.read("/session")(lambda ctx: {})
    with pytest.raises(ValueError):
        admin.read("/commands/x")(lambda ctx: {})
    with pytest.raises(ValueError):
        admin.command("Bad Name")


def test_mounts_inside_another_starlette_app(tmp_path):
    admin, calls, _ = build(tmp_path)
    parent = Starlette(routes=[Mount("/admin", app=admin.asgi())])
    client = TestClient(parent, base_url="https://testserver", headers=OPERATOR)
    assert client.get("/admin/healthz").json() == {"ok": True}
    assert client.get("/admin/api/runs").status_code == 200
    token = client.get("/admin/api/session").json()["csrf"]
    headers = {"X-Requested-With": "ledger-admin", "X-CSRF-Token": token, "Idempotency-Key": "k"}
    assert client.post("/admin/api/commands/decide", json={}, headers=headers).status_code == 200
    anonymous = TestClient(parent, base_url="https://testserver")
    assert anonymous.get("/admin/api/runs").status_code == 401
    assert anonymous.get("/admin/healthz").status_code == 200


# --- network auth: no identity, same command guard ----------------------------


def _network_admin():
    admin = Admin("bookmarks", auth="network")

    @admin.read("/things")
    def things(ctx):
        return {"actor": ctx.actor}

    @admin.command("mark")
    def mark(ctx, body):
        return {"by": ctx.actor}

    return admin


def test_network_auth_needs_no_identity_headers():
    client = TestClient(_network_admin().asgi(), base_url="http://listener.example:8879")
    session = client.get("/api/session").json()
    assert session["auth"] == "network" and session["actor"] == "network:unidentified" and session["can_command"] is True
    assert client.get("/api/things").json() == {"actor": "network:unidentified"}
    assert "secure" not in client.get("/api/session").headers["set-cookie"].lower()


def test_network_auth_names_a_tailscale_user_when_the_proxy_does():
    client = TestClient(_network_admin().asgi(), base_url="http://listener.example:8879", headers={"tailscale-user-login": "ada@example.com"})
    assert client.get("/api/things").json() == {"actor": "tailscale:ada@example.com"}


def test_network_auth_still_guards_commands():
    client = TestClient(_network_admin().asgi(), base_url="http://listener.example:8879")
    token = client.get("/api/session").json()["csrf"]
    assert client.post("/api/commands/mark", json={}).status_code in (400, 403)
    ok = client.post("/api/commands/mark", json={}, headers={
        "X-Requested-With": "bookmarks-admin", "X-CSRF-Token": token, "Idempotency-Key": "k-1", "Origin": "http://listener.example:8879"})
    assert ok.status_code == 200 and ok.json() == {"by": "network:unidentified"}
    cross = client.post("/api/commands/mark", json={}, headers={
        "X-Requested-With": "bookmarks-admin", "X-CSRF-Token": token, "Idempotency-Key": "k-2", "Origin": "http://evil.example"})
    assert cross.status_code == 403


def test_network_auth_rejects_groups():
    with pytest.raises(ValueError):
        Admin("bookmarks", auth="network", allowed_groups={"staff"})


def test_listed_origins_add_to_the_host_check():
    admin = Admin("bookmarks", auth="network", origins={"https://proxy.example"})

    @admin.command("mark")
    def mark(ctx, body):
        return {"ok": True}

    client = TestClient(admin.asgi(), base_url="http://listener.example:8879")
    token = client.get("/api/session").json()["csrf"]

    def post(origin, key):
        return client.post("/api/commands/mark", json={}, headers={
            "X-Requested-With": "bookmarks-admin", "X-CSRF-Token": token, "Idempotency-Key": key, "Origin": origin}).status_code

    assert post("https://proxy.example", "o-1") == 200
    assert post("http://listener.example:8879", "o-2") == 200
    assert post("http://evil.example", "o-3") == 403
