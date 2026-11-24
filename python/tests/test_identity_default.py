"""The default identity behaviour, pinned byte for byte so a provider seam
cannot change what existing admins send or accept."""
from __future__ import annotations

import json

from starlette.testclient import TestClient

from wheelhouse import Admin

OPERATOR = {"x-authentik-uid": "human:ada", "x-authentik-groups": "staff|admins"}


def build(**kwargs):
    kwargs.setdefault("allowed_groups", {"admins"})
    admin = Admin("ledger", **kwargs)

    @admin.read("/me")
    def me(ctx):
        return {"actor": ctx.actor, "groups": sorted(ctx.groups)}

    return admin


def client(admin, headers=OPERATOR):
    return TestClient(admin.asgi(), base_url="https://testserver", headers=headers)


def exact(payload):
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()


def test_session_bytes_are_unchanged():
    response = client(build()).get("/api/session")
    token = response.json()["csrf"]
    assert response.content == exact({"actor": "human:ada", "groups": ["admins", "staff"], "csrf": token,
                                      "app": "ledger", "auth": "authentik", "can_command": True})
    headers = {k.lower(): v for k, v in response.headers.items()}
    assert headers["cache-control"] == "private, no-store"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "same-origin"
    assert headers["x-frame-options"] == "DENY"
    assert headers["set-cookie"] == f"ledger_csrf={token}; HttpOnly; Path=/; SameSite=strict; Secure"


def test_dev_and_network_session_bytes_are_unchanged():
    dev = client(build(dev=True), headers={"x-authentik-uid": "human:mallory"}).get("/api/session")
    assert dev.content == exact({"actor": "human:dev", "groups": ["admins"], "csrf": dev.json()["csrf"],
                                 "app": "ledger", "auth": "dev", "can_command": True})
    net = TestClient(Admin("bookmarks", auth="network").asgi(), base_url="http://listener.example:8879").get("/api/session")
    assert net.content == exact({"actor": "network:unidentified", "groups": ["network"], "csrf": net.json()["csrf"],
                                 "app": "bookmarks", "auth": "network", "can_command": True})


def test_default_reads_uid_and_pipe_groups_only():
    admin = build()
    weird = {"x-authentik-uid": "  human:ada  ", "x-authentik-groups": " admins || staff |",
             "x-authentik-name": "Ada Lovelace", "x-authentik-username": "ada", "x-authentik-email": "ada@example.org"}
    response = client(admin, weird)
    assert response.get("/api/me").json() == {"actor": "human:ada", "groups": ["admins", "staff"]}
    # No name header is read by default, so the session has no display_name.
    assert "display_name" not in response.get("/api/session").json()


def test_default_refusals_are_unchanged():
    admin = build()
    assert client(admin, {}).get("/api/me").content == exact({"error": "Sign-in required"})
    assert client(admin, {"x-authentik-uid": "  "}).get("/api/me").status_code == 401
    refused = client(admin, {"x-authentik-uid": "human:eve", "x-authentik-groups": "staff"}).get("/api/me")
    assert refused.status_code == 403 and refused.content == exact({"error": "Access denied"})
    # Comma-separated groups are not split: only the pipe is a separator.
    comma = client(admin, {"x-authentik-uid": "human:eve", "x-authentik-groups": "staff,admins"})
    assert comma.get("/api/me").status_code == 403
