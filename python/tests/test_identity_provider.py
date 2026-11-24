"""The identity provider seam: Admin(identify=...), public routes, display names.
The command guard must refuse exactly the same requests under every provider."""
from __future__ import annotations

import asyncio

import pytest
from starlette.responses import RedirectResponse
from starlette.testclient import TestClient

from wheelhouse import Admin, AdminError, Identity, proxy_headers

PEOPLE = {
    "tok-ada": Identity("human:ada", {"desk-editors", "desk-reporters"}, "Ada Lovelace"),
    "tok-rae": Identity("human:rae", {"desk-readers"}),
}
LINKS = {"link-ada": "tok-ada", "link-rae": "tok-rae"}


def links_provider(calls=None):
    """A self-hosted provider: a session cookie set by a public sign-in route."""

    def identify(request):
        if calls is not None:
            calls.append(request.url.path)
        return PEOPLE.get(request.cookies.get("desk_session", ""))

    return identify


def build(identify=None, calls=None, **kwargs):
    kwargs.setdefault("allowed_groups", {"desk-readers", "desk-reporters", "desk-editors"})
    kwargs.setdefault("command_groups", {"desk-reporters", "desk-editors"})
    admin = Admin("workbench", identify=identify if identify is not None else links_provider(calls), **kwargs)
    ran: list[dict] = []

    @admin.read("/me")
    def me(ctx):
        return {"actor": ctx.actor, "groups": sorted(ctx.groups), "name": ctx.display_name}

    @admin.command("note")
    def note(ctx, body):
        ran.append({"by": ctx.actor, **body})
        return {"ok": True, "by": ctx.actor, "n": len(ran)}

    @admin.public("/sign-in")
    def sign_in(request):
        token = LINKS.get(request.query_params.get("link", ""))
        if token is None:
            raise admin.AdminError("That sign-in link is not valid", 401)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie("desk_session", token, httponly=True, samesite="strict", secure=True)
        return response

    return admin, ran


def signed_in(admin, who="tok-ada"):
    client = TestClient(admin.asgi(), base_url="https://testserver", follow_redirects=False)
    if who:
        client.cookies.set("desk_session", who)
    return client


def guard_headers(client, **overrides):
    headers = {"X-Requested-With": "workbench-admin", "X-CSRF-Token": client.get("/api/session").json()["csrf"],
               "Idempotency-Key": "key-1"}
    headers.update(overrides)
    return {k: v for k, v in headers.items() if v is not None}


# --- the provider decides who, the gate decides whether ---------------------------

def test_provider_identity_reaches_handlers_and_session():
    admin, _ = build()
    client = signed_in(admin)
    assert client.get("/api/me").json() == {"actor": "human:ada", "groups": ["desk-editors", "desk-reporters"],
                                            "name": "Ada Lovelace"}
    session = client.get("/api/session").json()
    assert session["display_name"] == "Ada Lovelace"
    assert session["auth"] == "custom" and session["can_command"] is True
    rae = signed_in(admin, "tok-rae").get("/api/session").json()
    assert "display_name" not in rae and rae["can_command"] is False


def test_provider_returning_none_is_401_everywhere_but_healthz_and_public():
    admin, _ = build()
    anonymous = signed_in(admin, None)
    for path in ("/api/session", "/api/me", "/", "/api/nope"):
        response = anonymous.get(path)
        assert response.status_code == 401 and response.json() == {"error": "Sign-in required"}
    assert anonymous.post("/api/commands/note", json={}).status_code == 401
    assert anonymous.get("/healthz").status_code == 200


def test_provider_groups_must_overlap_allowed_groups():
    admin, _ = build(identify=lambda request: Identity("human:eve", {"elsewhere"}))
    response = signed_in(admin, None).get("/api/me")
    assert response.status_code == 403 and response.json() == {"error": "Access denied"}


def test_an_empty_actor_is_not_an_identity():
    admin, _ = build(identify=lambda request: Identity("  ", {"desk-editors"}))
    assert signed_in(admin, None).get("/api/me").status_code == 401


def test_async_provider():
    async def identify(request):
        await asyncio.sleep(0)
        return Identity("human:ada", ["desk-editors"])

    admin, _ = build(identify=identify)
    assert signed_in(admin, None).get("/api/me").json()["actor"] == "human:ada"


def test_provider_is_asked_once_per_request():
    calls: list[str] = []
    admin, _ = build(calls=calls)
    client = signed_in(admin)
    client.get("/api/me")
    assert calls == ["/api/me"]


def test_provider_may_refuse_with_its_own_message():
    def identify(request):
        raise AdminError("Your sign-in link has expired", 401)

    admin, _ = build(identify=identify)
    response = signed_in(admin, None).get("/api/me")
    assert response.status_code == 401 and response.json() == {"error": "Your sign-in link has expired"}
    assert response.headers["x-frame-options"] == "DENY"


@pytest.mark.parametrize("result", [("human:ada", {"desk-editors"}), "human:ada", {"actor": "human:ada"}])
def test_provider_returning_the_wrong_type_is_a_500_not_a_sign_in(result, caplog):
    admin, ran = build(identify=lambda request: result)
    client = signed_in(admin, None)
    response = client.get("/api/me")
    assert response.status_code == 500 and response.json() == {"error": "Internal error"}
    assert client.post("/api/commands/note", json={}).status_code == 500
    assert ran == []


def test_provider_crash_does_not_leak(caplog):
    def identify(request):
        raise RuntimeError("secret session store path")

    admin, _ = build(identify=identify)
    response = signed_in(admin, None).get("/api/me")
    assert response.status_code == 500 and "secret" not in response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert "secret session store path" in caplog.text


def test_dev_mode_ignores_the_provider():
    calls: list[str] = []
    admin, _ = build(calls=calls, dev=True)
    client = signed_in(admin, None)
    assert client.get("/api/me").json()["actor"] == "human:dev"
    assert client.get("/api/session").json()["auth"] == "dev"
    assert calls == []


def test_identity_refuses_a_string_of_groups():
    with pytest.raises(TypeError):
        Identity("human:ada", "desk-editors")
    assert Identity("human:ada", ["a", "a"]).groups == frozenset({"a"})


def test_constructor_checks():
    with pytest.raises(ValueError):
        Admin("workbench", identify=links_provider(), auth="network")
    with pytest.raises(TypeError):
        Admin("workbench", identify="x-authentik-uid", allowed_groups={"g"})  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Admin("workbench", identify=links_provider(), auth="Local Links", allowed_groups={"g"})
    labelled = Admin("workbench", identify=links_provider(), auth="links", allowed_groups={"desk-editors"})
    client = signed_in(labelled)
    assert client.get("/api/session").json()["auth"] == "links"


def test_mode_variable_accepts_the_provider_label(monkeypatch):
    monkeypatch.setenv("WORKBENCH_ADMIN_MODE", "links")
    assert Admin("workbench", identify=links_provider(), auth="links", allowed_groups={"g"}).dev is False
    monkeypatch.setenv("WORKBENCH_ADMIN_MODE", "dev")
    assert Admin("workbench", identify=links_provider(), auth="links", allowed_groups={"g"}).dev is True
    monkeypatch.setenv("WORKBENCH_ADMIN_MODE", "network")
    with pytest.raises(ValueError):
        Admin("workbench", identify=links_provider(), auth="links", allowed_groups={"g"})


# --- the proxy provider, with a name header -------------------------------------

def test_proxy_headers_with_a_name_header():
    admin = Admin("ledger", allowed_groups={"admins"}, identify=proxy_headers(name="x-authentik-name"))

    @admin.read("/me")
    def me(ctx):
        return {"actor": ctx.actor, "name": ctx.display_name}

    client = TestClient(admin.asgi(), base_url="https://testserver", headers={
        "x-authentik-uid": "human:ada", "x-authentik-groups": "admins", "x-authentik-name": " Ada Lovelace "})
    assert client.get("/api/me").json() == {"actor": "human:ada", "name": "Ada Lovelace"}
    session = client.get("/api/session").json()
    assert session["display_name"] == "Ada Lovelace" and session["auth"] == "authentik"
    nameless = TestClient(admin.asgi(), base_url="https://testserver", headers={
        "x-authentik-uid": "human:ada", "x-authentik-groups": "admins", "x-authentik-name": "  "})
    assert "display_name" not in nameless.get("/api/session").json()


def test_proxy_headers_other_names():
    admin = Admin("ledger", allowed_groups={"staff"},
                  identify=proxy_headers(uid="remote-user", groups="remote-groups", separator=","))
    client = TestClient(admin.asgi(), base_url="https://testserver",
                        headers={"remote-user": "human:ada", "remote-groups": "staff, other"})
    assert client.get("/api/session").json()["groups"] == ["other", "staff"]
    # The default headers mean nothing to this provider.
    other = TestClient(admin.asgi(), base_url="https://testserver",
                       headers={"x-authentik-uid": "human:ada", "x-authentik-groups": "staff"})
    assert other.get("/api/session").status_code == 401


# --- public routes: outside the identity gate, inside the headers ---------------

def test_public_route_needs_no_identity_but_carries_the_security_headers():
    calls: list[str] = []
    admin, _ = build(calls=calls)
    client = signed_in(admin, None)
    response = client.get("/sign-in?link=link-ada")
    assert response.status_code == 303 and response.headers["location"] == "/"
    for header, value in {"cache-control": "private, no-store", "x-content-type-options": "nosniff",
                          "referrer-policy": "same-origin", "x-frame-options": "DENY"}.items():
        assert response.headers[header] == value
    assert calls == []  # the provider was not consulted for the public route
    assert client.get("/api/me").json()["actor"] == "human:ada"  # the cookie now signs in


def test_public_route_errors_are_shaped():
    admin, _ = build()
    response = signed_in(admin, None).get("/sign-in?link=forged")
    assert response.status_code == 401 and response.json() == {"error": "That sign-in link is not valid"}
    assert response.headers["x-frame-options"] == "DENY"


def test_public_route_is_exact_path_and_method():
    admin, _ = build()
    anonymous = signed_in(admin, None)
    assert anonymous.post("/sign-in?link=link-ada").status_code == 401  # only GET is public
    assert anonymous.get("/sign-in/extra").status_code == 401
    assert anonymous.get("/sign-in/").status_code == 401
    assert anonymous.get("/SIGN-IN?link=link-ada").status_code == 401
    assert anonymous.head("/sign-in?link=link-ada").status_code == 303


def test_public_route_under_a_mount():
    from starlette.applications import Starlette
    from starlette.routing import Mount

    admin, _ = build()
    parent = Starlette(routes=[Mount("/desk", app=admin.asgi())])
    client = TestClient(parent, base_url="https://testserver", follow_redirects=False)
    assert client.get("/desk/api/me").status_code == 401
    assert client.get("/desk/sign-in?link=link-ada").status_code == 303
    assert client.get("/desk/api/me").json()["actor"] == "human:ada"
    assert client.get("/sign-in?link=link-ada").status_code == 404  # outside the mount: not this app


def test_public_route_registration_rules():
    admin, _ = build()
    for path in ("/healthz", "/api/session", "/api/commands/note", "/api/commands", "/", "sign-up", "/a/{id}"):
        with pytest.raises(ValueError):
            admin.public(path)(lambda request: {})
    with pytest.raises(ValueError):
        admin.public("/sign-in")(lambda request: {})  # already registered
    with pytest.raises(ValueError):
        admin.public("/hook", methods=("PUT", "BREW"))(lambda request: {})
    admin.public("/hook", methods=("POST",))(lambda request: {"ok": True})
    client = signed_in(admin, None)
    response = client.post("/hook")
    assert response.status_code == 200 and response.json() == {"ok": True}


def test_public_route_does_not_open_the_api_paths_it_shadows():
    admin, _ = build()
    admin.public("/api/sign-in/exchange", methods=("POST",))(lambda request: {"ok": True})
    anonymous = signed_in(admin, None)
    assert anonymous.post("/api/sign-in/exchange").json() == {"ok": True}
    assert anonymous.get("/api/sign-in/exchange").status_code == 401
    assert anonymous.get("/api/me").status_code == 401


# --- the command guard is the same under every provider --------------------------

def network_admin():
    admin = Admin("workbench", auth="network")

    @admin.command("note")
    def note(ctx, body):
        return {"ok": True, "by": ctx.actor}

    return admin, TestClient(admin.asgi(), base_url="https://testserver")


def proxy_admin():
    admin = Admin("workbench", allowed_groups={"desk-editors"})

    @admin.command("note")
    def note(ctx, body):
        return {"ok": True, "by": ctx.actor}

    return admin, TestClient(admin.asgi(), base_url="https://testserver",
                             headers={"x-authentik-uid": "human:ada", "x-authentik-groups": "desk-editors"})


def links_admin():
    admin, _ = build()
    return admin, signed_in(admin)


PROVIDERS = {"proxy": proxy_admin, "links": links_admin, "network": network_admin}
REFUSALS = [
    ({"X-Requested-With": None}, 403),
    ({"X-Requested-With": "tally-admin"}, 403),
    ({"X-CSRF-Token": None}, 403),
    ({"X-CSRF-Token": "not-the-token"}, 403),
    ({"Idempotency-Key": None}, 400),
    ({"Idempotency-Key": "k" * 201}, 400),
    ({"Origin": "https://evil.example"}, 403),
    ({"Origin": "null"}, 403),
    ({"Sec-Fetch-Site": "cross-site"}, 403),
    ({"Sec-Fetch-Site": "same-site", "Origin": "https://testserver"}, 403),
]


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
@pytest.mark.parametrize("overrides,status", REFUSALS)
def test_every_provider_gets_the_same_command_refusals(provider, overrides, status):
    _, client = PROVIDERS[provider]()
    response = client.post("/api/commands/note", json={"x": 1}, headers=guard_headers(client, **overrides))
    assert response.status_code == status
    assert set(response.json()) == {"error"}


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_every_provider_accepts_a_good_command_and_replays_it(provider):
    _, client = PROVIDERS[provider]()
    headers = guard_headers(client, Origin="https://testserver", **{"Sec-Fetch-Site": "same-origin"})
    first = client.post("/api/commands/note", json={"x": 1}, headers=headers)
    again = client.post("/api/commands/note", json={"x": 1}, headers=headers)
    assert first.status_code == again.status_code == 200
    assert again.headers["idempotent-replay"] == "true" and again.json() == first.json()
    assert client.post("/api/commands/note", json={"x": 2}, headers=headers).status_code == 422


def test_links_provider_command_groups_and_session_cookie():
    admin, ran = build()
    reader = signed_in(admin, "tok-rae")
    response = reader.post("/api/commands/note", json={}, headers=guard_headers(reader))
    assert response.status_code == 403 and response.json() == {"error": "Your groups may not issue commands"}
    # A token fetched by one person does not let another person's cookie through.
    ada = signed_in(admin)
    token = ada.get("/api/session").json()["csrf"]
    other = signed_in(admin, "tok-ada")
    stolen = {"X-Requested-With": "workbench-admin", "X-CSRF-Token": token, "Idempotency-Key": "k"}
    assert other.post("/api/commands/note", json={}, headers=stolen).status_code == 403
    assert ran == []


def test_idempotency_is_per_provider_actor():
    admin, ran = build(command_groups={"desk-reporters", "desk-editors", "desk-readers"})
    ada, rae = signed_in(admin), signed_in(admin, "tok-rae")
    ada.post("/api/commands/note", json={}, headers=guard_headers(ada))
    response = rae.post("/api/commands/note", json={}, headers=guard_headers(rae))
    assert response.json()["by"] == "human:rae" and "idempotent-replay" not in response.headers
    assert [r["by"] for r in ran] == ["human:ada", "human:rae"]
