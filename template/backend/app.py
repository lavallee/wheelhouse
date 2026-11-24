"""The admin API. Reads and commands are plain functions; the wheelhouse
package supplies identity, the command guard, idempotency, ETags and the
built UI. Swap `sample.Store` for the app's real store.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from wheelhouse import Admin, Event

from sample import Store

APP_ID = "sample"
store = Store()

admin = Admin(
    app=APP_ID,
    web_dir=Path(__file__).resolve().parent.parent / "web",
    allowed_groups={"admins"},
)


@admin.read("/overview")
def overview(ctx):
    runs = store.runs
    return {"stats": store.counts(), "needs_you": store.queue()[:5], "latest_run": runs[-1] if runs else None}


@admin.read("/items")
def items(ctx):
    q = ctx.query
    rows, facets = store.search(q.get("status", ""), q.get("source", ""), q.get("q", ""), q.get("sort", ""))
    return {**admin.page(rows, ctx, default_limit=25), "facets": facets}


@admin.read("/items/{item_id}")
def item(ctx):
    found = store.find(ctx.path_params["item_id"])
    if found is None:
        raise admin.NotFound("No submission with that id")
    return {"item": found}


@admin.read("/queue")
def queue(ctx):
    waiting = store.queue()
    return {"items": waiting[:10], "total": len(waiting)}


@admin.read("/runs")
def runs(ctx):
    return {"runs": list(reversed(store.runs)), "estimate": store.estimate(), "budget": store.budget}


@admin.read("/runs/{run_id}")
def run_detail(ctx):
    found = store.find_run(ctx.path_params["run_id"])
    if found is None:
        raise admin.NotFound("No run with that id")
    return found


@admin.stream("/activity/stream")
async def activity(ctx):
    """The activity journal as events. A first connection gets the latest 30
    rows, a reconnection everything after the id it last saw; then `ready`,
    then each new row as it is written."""
    try:
        seen = int(ctx.last_event_id) if ctx.last_event_id else None
    except ValueError:
        seen = None
    if seen is not None and seen > len(store.activity):
        seen = None  # the journal is shorter than the id: it was reset (the sample lives in memory)
    backlog = store.activity_after(seen) if seen is not None else store.activity_after(0, limit=30)
    for row in backlog:
        yield Event(row, id=row["seq"], event="activity")
    seen = backlog[-1]["seq"] if backlog else (seen or len(store.activity))
    yield Event({"backlog": len(backlog)}, event="ready")
    while True:
        await asyncio.sleep(1)
        for row in store.activity_after(seen):
            yield Event(row, id=row["seq"], event="activity")
            seen = row["seq"]


@admin.read("/settings")
def settings(ctx):
    return {"budget": store.budget, "cli": f"{APP_ID} run --budget {store.budget['dollars_per_run']:g}"}


@admin.command("review")
def review(ctx, body):
    try:
        return {"item": store.review(str(body.get("id", "")), str(body.get("decision", "")), str(body.get("note", "")), ctx.actor)}
    except LookupError as error:
        raise admin.NotFound(str(error))
    except ValueError as error:
        raise admin.Invalid(str(error))


@admin.command("budget")
def budget(ctx, body):
    try:
        return {"budget": store.set_budget(float(body.get("dollars_per_run", 0)), int(body.get("items_per_run", 0)), ctx.actor)}
    except (TypeError, ValueError) as error:
        raise admin.Invalid(str(error) if "Budget" in str(error) else "Both budget fields must be numbers")


@admin.command("run")
def run(ctx, body):
    try:
        return {"run": store.start_run(ctx.actor)}
    except ValueError as error:
        raise admin.Conflict(str(error))


app = admin.asgi()
