"""The template's own checks: the sample API answers in the shapes the UI reads."""
import os

os.environ["SAMPLE_ADMIN_MODE"] = "dev"

from starlette.testclient import TestClient  # noqa: E402

import app as module  # noqa: E402

client = TestClient(module.app, base_url="http://testserver")


def command(name, body):
    session = client.get("/api/session").json()
    return client.post(f"/api/commands/{name}", json=body, headers={
        "X-Requested-With": f"{module.APP_ID}-admin", "X-CSRF-Token": session["csrf"],
        "Idempotency-Key": os.urandom(8).hex(), "Origin": "http://testserver"})


def test_overview_and_list_shapes():
    overview = client.get("/api/overview").json()
    assert set(overview) == {"stats", "needs_you", "latest_run"}
    page = client.get("/api/items?status=new&limit=10").json()
    assert len(page["items"]) == 10 and page["total"] == overview["stats"]["new"]
    assert set(page["facets"]) == {"status", "source"}


def test_missing_item_is_a_json_404():
    response = client.get("/api/items/SUB-9999")
    assert response.status_code == 404 and "error" in response.json()


def test_review_round_trip():
    first = client.get("/api/queue").json()["items"][0]
    assert command("review", {"id": first["id"], "decision": "approve", "note": ""}).status_code == 200
    assert client.get(f"/api/items/{first['id']}").json()["item"]["status"] == "approved"
    assert command("review", {"id": first["id"], "decision": "reopen", "note": ""}).status_code == 200
    assert command("review", {"id": first["id"], "decision": "nonsense", "note": ""}).status_code == 422


def test_command_without_guard_headers_is_refused():
    assert client.post("/api/commands/run", json={}).status_code in (400, 403)


def test_run_detail_shape():
    run = client.get("/api/runs").json()["runs"][0]
    detail = client.get(f"/api/runs/{run['id']}").json()
    assert set(detail) == {"run", "items", "log"} and detail["run"]["id"] == run["id"]
    assert client.get("/api/runs/RUN-999").status_code == 404


def _take(ctx_after, count):
    """Read `count` events from the activity stream handler, then close it."""
    import asyncio
    from types import SimpleNamespace

    async def run():
        source = module.activity(SimpleNamespace(last_event_id=ctx_after))
        got = [await source.__anext__() for _ in range(count)]
        await source.aclose()
        return got

    return asyncio.run(run())


def test_activity_stream_backlog_then_ready_then_resume():
    first = _take(None, 31)
    assert [e.event for e in first[:30]] == ["activity"] * 30 and first[30].event == "ready"
    ids = [e.id for e in first[:30]]
    assert ids == sorted(ids) and ids[-1] == len(module.store.activity)
    # Resuming after an id sends only what came after it.
    resumed = _take(str(ids[-3]), 3)
    assert [e.id for e in resumed[:2]] == ids[-2:] and resumed[2].event == "ready"
    # A review appears in the journal with the reviewer as actor.
    item = client.get("/api/queue").json()["items"][0]
    command("review", {"id": item["id"], "decision": "hold", "note": ""})
    assert module.store.activity[-1]["target"] == item["id"] and module.store.activity[-1]["actor"] == "human:dev"
