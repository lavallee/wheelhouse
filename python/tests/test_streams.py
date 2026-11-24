"""Event streams: ids and names, resuming, keep-alive, and stopping when the client leaves."""
from __future__ import annotations

import asyncio

import pytest
from starlette.testclient import TestClient

from wheelhouse import Admin, Event

OPERATOR = {"x-authentik-uid": "human:ada", "x-authentik-groups": "admins"}
JOURNAL = [f"row {n}" for n in range(1, 6)]


def client_for(admin, headers=OPERATOR):
    return TestClient(admin.asgi(), base_url="https://testserver", headers=headers)


def blocks(text):
    return [block for block in text.split("\n\n") if block and not block.startswith(":")]


def comments(text):
    return [block for block in text.split("\n\n") if block.startswith(":")]


@pytest.fixture
def admin():
    admin = Admin("ledger", allowed_groups={"admins"})

    @admin.stream("/journal")
    async def journal(ctx):
        start = int(ctx.last_event_id or 0)
        for n, row in enumerate(JOURNAL[start:], start=start + 1):
            yield Event({"row": row}, id=n, event="row")

    @admin.stream("/tuples")
    def tuples(ctx):
        return iter([(1, "plain"), (2, "named", "with a name"), "bare"])

    @admin.stream("/seen")
    async def seen(ctx):
        yield f"{ctx.last_event_id}"

    return admin


def test_events_carry_ids_names_and_json(admin):
    text = client_for(admin).get("/api/journal").text
    assert blocks(text)[0] == 'event: row\nid: 1\ndata: {"row":"row 1"}'
    assert len(blocks(text)) == 5


def test_tuples_and_bare_strings(admin):
    assert blocks(client_for(admin).get("/api/tuples").text) == [
        "id: 1\ndata: plain", "event: named\nid: 2\ndata: with a name", "data: bare"]


def test_resume_from_last_event_id_header_or_after_query(admin):
    client = client_for(admin)
    by_header = blocks(client.get("/api/journal", headers={"Last-Event-ID": "3"}).text)
    assert [b.split("\n")[1] for b in by_header] == ["id: 4", "id: 5"]
    by_query = blocks(client.get("/api/journal?after=4").text)
    assert [b.split("\n")[1] for b in by_query] == ["id: 5"]
    # The header is what the browser sends on its own reconnect, so it wins.
    assert blocks(client.get("/api/seen?after=1", headers={"Last-Event-ID": "2"}).text) == ["data: 2"]
    assert blocks(client.get("/api/seen").text) == ["data: None"]


def test_multiline_data_splits_only_on_line_breaks():
    admin = Admin("ledger", allowed_groups={"admins"})

    @admin.stream("/odd")
    async def odd(ctx):
        yield Event("a\r\nb c")

    assert blocks(client_for(admin).get("/api/odd").text) == ["data: a\ndata: b c"]


@pytest.mark.parametrize("bad", [Event("x", id="1\n2"), Event("x", id="a\0"), Event("x", event="two\nlines"), Event("x", event="")])
def test_an_unsafe_id_or_name_ends_the_stream_with_an_error(bad):
    admin = Admin("ledger", allowed_groups={"admins"})

    @admin.stream("/bad")
    async def bad_stream(ctx):
        yield "fine"
        yield bad

    assert blocks(client_for(admin).get("/api/bad").text) == ["data: fine", "event: error\ndata: Stream failed"]


def test_keepalive_comment_on_a_quiet_stream():
    admin = Admin("ledger", allowed_groups={"admins"})

    @admin.stream("/quiet", keepalive=0.02)
    async def quiet(ctx):
        await asyncio.sleep(0.15)
        yield "late"

    text = client_for(admin).get("/api/quiet").text
    assert blocks(text) == ["data: late"]
    assert comments(text)[0] == ": open"
    assert ": keep-alive" in comments(text)


def test_keepalive_can_be_turned_off():
    admin = Admin("ledger", allowed_groups={"admins"})

    @admin.stream("/quiet", keepalive=None)
    async def quiet(ctx):
        await asyncio.sleep(0.1)
        yield "late"

    assert comments(client_for(admin).get("/api/quiet").text) == [": open"]
    with pytest.raises(ValueError):
        admin.stream("/x", keepalive=-1)


def test_default_keepalive_is_about_twenty_seconds():
    from wheelhouse import admin as module
    assert 10 <= module.KEEPALIVE_SECONDS <= 30


def test_client_disconnect_cancels_and_closes_the_handler():
    """A handler waiting on something that never comes is cancelled and its
    cleanup runs as soon as the client goes, not at the next write."""
    admin = Admin("ledger", allowed_groups={"admins"})
    state = {"closed": False, "cancelled": False}

    @admin.stream("/forever", keepalive=None)
    async def forever(ctx):
        try:
            yield "hello"
            await asyncio.Event().wait()
            yield "never"
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise
        finally:
            state["closed"] = True

    app = admin.asgi()

    async def run():
        sent = []
        first_body = asyncio.Event()
        calls = 0

        async def receive():
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"type": "http.request", "body": b"", "more_body": False}
            await first_body.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)
            if message["type"] == "http.response.body" and b"hello" in message.get("body", b""):
                first_body.set()

        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}, "http_version": "1.1",
                 "method": "GET", "scheme": "https", "path": "/api/forever", "raw_path": b"/api/forever",
                 "root_path": "", "query_string": b"", "server": ("testserver", 443), "client": ("1.2.3.4", 1),
                 "headers": [(k.encode(), v.encode()) for k, v in OPERATOR.items()] + [(b"host", b"testserver")]}
        await asyncio.wait_for(app(scope, receive, send), timeout=2)
        return sent

    sent = asyncio.run(run())
    assert sent[0]["status"] == 200
    assert state == {"closed": True, "cancelled": True}
    assert not any(b"never" in m.get("body", b"") for m in sent)


def test_plain_string_streams_are_unchanged():
    admin = Admin("ledger", allowed_groups={"admins"})

    @admin.stream("/logs")
    async def logs(ctx):
        yield "one\ntwo"

    response = client_for(admin).get("/api/logs")
    assert response.text == ": open\n\ndata: one\ndata: two\n\n"
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["content-type"].startswith("text/event-stream")
