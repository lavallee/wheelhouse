"""Startup and shutdown hooks run in the ASGI lifespan."""
from __future__ import annotations

import asyncio

import pytest
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from wheelhouse import Admin

OPERATOR = {"x-authentik-uid": "human:ada", "x-authentik-groups": "admins"}


def test_hooks_run_in_order_sync_and_async():
    admin = Admin("ledger", allowed_groups={"admins"})
    seen: list[str] = []

    @admin.on_startup
    def open_store():
        seen.append("open store")

    @admin.on_startup
    async def start_hub():
        await asyncio.sleep(0)
        seen.append("start hub")

    @admin.on_shutdown
    async def stop_hub():
        seen.append("stop hub")

    @admin.on_shutdown
    def close_store():
        seen.append("close store")

    @admin.read("/seen")
    def read_seen(ctx):
        return list(seen)

    with TestClient(admin.asgi(), base_url="https://testserver", headers=OPERATOR) as client:
        assert client.get("/api/seen").json() == ["open store", "start hub"]
    # Shutdown runs in reverse order of registration.
    assert seen == ["open store", "start hub", "close store", "stop hub"]
    assert open_store.__name__ == "open_store"  # the decorator returns the function


def test_a_failing_startup_hook_stops_the_server_starting():
    admin = Admin("ledger", allowed_groups={"admins"})
    stopped = []

    @admin.on_startup
    def refuse():
        raise RuntimeError("another worker already owns this desk")

    admin.on_shutdown(lambda: stopped.append(True))
    with pytest.raises(RuntimeError, match="already owns"):
        with TestClient(admin.asgi()):
            pass
    assert stopped == []  # nothing started, so nothing to stop


def test_a_failing_shutdown_hook_does_not_skip_the_others(caplog):
    admin = Admin("ledger", allowed_groups={"admins"})
    stopped = []
    admin.on_shutdown(lambda: stopped.append("first registered"))

    @admin.on_shutdown
    def broken():
        raise RuntimeError("flush failed")

    with TestClient(admin.asgi()):
        pass
    assert stopped == ["first registered"]
    assert "a shutdown hook failed" in caplog.text


def test_a_parent_app_runs_the_hooks_through_admin_lifespan():
    admin = Admin("ledger", allowed_groups={"admins"})
    seen = []
    admin.on_startup(lambda: seen.append("up"))
    admin.on_shutdown(lambda: seen.append("down"))
    parent = Starlette(routes=[Mount("/admin", app=admin.asgi())], lifespan=admin.lifespan)
    with TestClient(parent, base_url="https://testserver", headers=OPERATOR) as client:
        assert client.get("/admin/healthz").json() == {"ok": True}
        assert seen == ["up"]
    assert seen == ["up", "down"]


def test_no_hooks_is_fine():
    admin = Admin("ledger", allowed_groups={"admins"})
    with TestClient(admin.asgi()) as client:
        assert client.get("/healthz").status_code == 200
