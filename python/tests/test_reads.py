"""Reads that bring their own ETag: an etag= callable, or Cached bytes."""
from __future__ import annotations

import hashlib
import json

import pytest
from starlette.responses import PlainTextResponse
from starlette.testclient import TestClient

from wheelhouse import Admin, Cached

OPERATOR = {"x-authentik-uid": "human:ada", "x-authentik-groups": "admins"}


def client_for(admin):
    return TestClient(admin.asgi(), base_url="https://testserver", headers=OPERATOR)


@pytest.fixture
def picture():
    """A hub that holds one resource serialised once, with a revision number."""
    admin = Admin("ledger", allowed_groups={"admins"})
    hub = {"rev": 3, "bytes": json.dumps({"claims": 12}).encode(), "handler_calls": 0, "etag_calls": 0}

    def current(ctx):
        hub["etag_calls"] += 1
        return f"rev-{hub['rev']}"

    @admin.read("/picture", etag=current)
    def picture_read(ctx):
        hub["handler_calls"] += 1
        return Cached(hub["bytes"])

    @admin.read("/cached")
    async def cached(ctx):
        hub["handler_calls"] += 1
        return Cached(hub["bytes"], etag=f'W/"{hub["rev"]}"')

    @admin.read("/hashed")
    def hashed(ctx):
        return Cached(hub["bytes"])

    @admin.read("/unknowable", etag=lambda ctx: None)
    def unknowable(ctx):
        return {"rev": hub["rev"]}

    @admin.read("/text")
    def text(ctx):
        return Cached(b"plain words", etag="t1", media_type="text/plain")

    @admin.read("/download")
    def download(ctx):
        return PlainTextResponse("a,b\n1,2\n")

    return admin, hub


def test_etag_callable_answers_304_without_calling_the_handler(picture):
    admin, hub = picture
    client = client_for(admin)
    first = client.get("/api/picture")
    assert first.status_code == 200 and first.json() == {"claims": 12}
    assert first.headers["etag"] == '"rev-3"'
    assert hub["handler_calls"] == 1
    again = client.get("/api/picture", headers={"If-None-Match": '"rev-3"'})
    assert again.status_code == 304 and again.headers["etag"] == '"rev-3"'
    assert hub["handler_calls"] == 1 and hub["etag_calls"] == 2
    hub["rev"] = 4
    changed = client.get("/api/picture", headers={"If-None-Match": '"rev-3"'})
    assert changed.status_code == 200 and changed.headers["etag"] == '"rev-4"'
    assert hub["handler_calls"] == 2


def test_cached_bytes_with_their_own_etag(picture):
    admin, hub = picture
    client = client_for(admin)
    first = client.get("/api/cached")
    assert first.content == hub["bytes"]
    assert first.headers["etag"] == 'W/"3"'
    assert first.headers["content-type"] == "application/json"
    assert client.get("/api/cached", headers={"If-None-Match": 'W/"3"'}).status_code == 304
    assert client.get("/api/cached", headers={"If-None-Match": '"3"'}).status_code == 304  # weak comparison


def test_cached_bytes_without_an_etag_are_hashed_not_reserialised(picture):
    admin, hub = picture
    response = client_for(admin).get("/api/hashed")
    assert response.content == hub["bytes"]
    assert response.headers["etag"] == '"' + hashlib.sha256(hub["bytes"]).hexdigest()[:32] + '"'


def test_an_etag_callable_that_cannot_tell_falls_back_to_the_hash(picture):
    admin, _ = picture
    client = client_for(admin)
    tag = client.get("/api/unknowable").headers["etag"]
    assert client.get("/api/unknowable", headers={"If-None-Match": tag}).status_code == 304


def test_cached_media_type_and_bypass_response_still_work(picture):
    admin, _ = picture
    client = client_for(admin)
    text = client.get("/api/text")
    assert text.headers["content-type"].startswith("text/plain") and text.text == "plain words"
    assert text.headers["etag"] == '"t1"'
    download = client.get("/api/download")
    assert download.text == "a,b\n1,2\n" and "etag" not in download.headers
    assert download.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("bad", ['has"quote', "line\nbreak", "sp ace", '"unclosed'])
def test_an_unusable_etag_is_an_internal_error(bad):
    admin = Admin("ledger", allowed_groups={"admins"})

    @admin.read("/bad")
    def bad_read(ctx):
        return Cached(b"{}", etag=bad)

    response = client_for(admin).get("/api/bad")
    assert response.status_code == 500 and response.json() == {"error": "Internal error"}


def test_cached_body_must_be_bytes():
    admin = Admin("ledger", allowed_groups={"admins"})

    @admin.read("/bad")
    def bad_read(ctx):
        return Cached("{}")  # type: ignore[arg-type]

    assert client_for(admin).get("/api/bad").status_code == 500


def test_the_etag_callable_is_behind_the_identity_gate(picture):
    admin, hub = picture
    anonymous = TestClient(admin.asgi(), base_url="https://testserver")
    assert anonymous.get("/api/picture").status_code == 401
    assert hub["etag_calls"] == 0
