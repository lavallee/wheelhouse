"""In-memory sample data for the template admin.

Replace this module with the app's real store. It exists so a newly
commissioned admin runs, with production-shaped volume, before any real data
is wired in. Everything here is invented and deterministic.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

SOURCES = ["field-desk", "partner-feed", "web-form", "email-intake", "archive-import"]
KINDS = ["report", "dataset", "correction", "tip"]
SUBJECTS = ["county budget", "school enrolment", "transit ridership", "water quality", "housing permits",
            "election returns", "court filings", "hospital capacity", "road closures", "library hours"]
ANGLES = ["update", "quarterly figures", "correction to prior release", "new source file", "follow-up request", "methodology note"]

REVIEWERS = ["human:sample", "human:okafor", "human:lindqvist", "human:reyes"]
STEPS = ["fetched", "parsed", "deduplicated", "classified", "scored", "queued for review"]
SORTABLE = {"title", "source", "received", "size", "status"}
DECISIONS = {"approve": "approved", "hold": "held", "reject": "rejected", "reopen": "new"}


class Store:
    def __init__(self, count: int = 137, seed: int = 7, now: datetime | None = None):
        rng = random.Random(seed)
        now = now or datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc)
        self.items: list[dict] = []
        for n in range(1, count + 1):
            received = now - timedelta(minutes=rng.randint(5, 60 * 24 * 21))
            status = rng.choices(["new", "approved", "rejected", "held"], weights=[30, 45, 15, 10])[0]
            self.items.append({
                "id": f"SUB-{n:04d}",
                "title": f"{rng.choice(SUBJECTS).capitalize()}: {rng.choice(ANGLES)}",
                "source": rng.choice(SOURCES),
                "kind": rng.choice(KINDS),
                "status": status,
                "received": received.isoformat(timespec="minutes"),
                "size": int(rng.lognormvariate(11, 2)),
                "url": f"https://example.org/submissions/{n}",
                "note": "" if rng.random() < 0.6 else "Sender asked for a reply before publication.",
                "reviewed_by": None if status == "new" else "human:sample",
            })
        self.runs: list[dict] = [
            {"id": f"RUN-{i:03d}", "started": (now - timedelta(days=d, hours=2)).isoformat(timespec="minutes"),
             "status": s, "items": k, "cost": c, "started_by": "timer"}
            for i, (d, s, k, c) in enumerate([(9, "ok", 31, 3.1), (6, "failed", 4, 0.4), (3, "ok", 42, 4.35), (1, "ok", 27, 2.7)], start=1)
        ]
        self.budget = {"dollars_per_run": 5.0, "items_per_run": 50}
        self._now = now
        # The activity journal: append-only, numbered from 1, so a stream can resume after any id.
        self.activity: list[dict] = []
        reviewed = sorted((i for i in self.items if i["status"] != "new"), key=lambda i: i["received"])
        for item in reviewed:
            at = datetime.fromisoformat(item["received"]) + timedelta(minutes=rng.randint(20, 60 * 30))
            verb = {"approved": "approved", "rejected": "rejected", "held": "held"}[item["status"]]
            self._log(min(at, now), rng.choice(REVIEWERS), verb, item["id"], item["title"])
        for run in self.runs:
            self._log(datetime.fromisoformat(run["started"]), "timer", "started", run["id"], f"{run['items']} submissions")
        self.activity.sort(key=lambda row: row["at"])
        for n, row in enumerate(self.activity, start=1):
            row["seq"] = n

    # --- reads -------------------------------------------------------------------
    def counts(self) -> dict:
        out = {"new": 0, "held": 0, "approved": 0, "rejected": 0}
        for item in self.items:
            out[item["status"]] += 1
        return out

    def queue(self) -> list[dict]:
        return sorted((i for i in self.items if i["status"] == "new"), key=lambda i: i["received"])

    def find_run(self, run_id: str) -> dict | None:
        """A run with the submissions it processed and its log. Invented, but stable per run."""
        run = next((r for r in self.runs if r["id"] == run_id), None)
        if run is None:
            return None
        rng = random.Random(run_id)
        started = datetime.fromisoformat(run["started"])
        processed = sorted(rng.sample(self.items, min(run["items"], len(self.items))), key=lambda i: i["id"])
        log, at = [], started
        for item in processed:
            for step in STEPS[: rng.randint(3, len(STEPS))]:
                at += timedelta(seconds=rng.randint(1, 40))
                log.append({"at": at.isoformat(timespec="seconds"), "level": "info", "text": f"{item['id']} {step}"})
        if run["status"] == "failed":
            log.append({"at": (at + timedelta(seconds=3)).isoformat(timespec="seconds"), "level": "error",
                        "text": "partner-feed answered 503 three times; run stopped"})
        return {"run": run, "items": processed, "log": log}

    def activity_after(self, seq: int, limit: int | None = None) -> list[dict]:
        rows = self.activity[seq:] if seq >= 0 else []
        return rows[-limit:] if limit else rows

    def find(self, item_id: str) -> dict | None:
        return next((i for i in self.items if i["id"] == item_id), None)

    def search(self, status: str = "", source: str = "", q: str = "", sort: str = "") -> tuple[list[dict], dict]:
        needle = q.strip().lower()
        text_match = [i for i in self.items if not needle or needle in i["title"].lower() or needle in i["note"].lower()]
        # Facet counts ignore their own filter, so the menu shows what each choice would give.
        facets = {
            "status": _tally(i["status"] for i in text_match if not source or i["source"] == source),
            "source": _tally(i["source"] for i in text_match if not status or i["status"] == status),
        }
        rows = [i for i in text_match if (not status or i["status"] == status) and (not source or i["source"] == source)]
        key = sort.lstrip("-")
        if key in SORTABLE:
            rows.sort(key=lambda i: (i[key].lower() if isinstance(i[key], str) else i[key]), reverse=sort.startswith("-"))
        else:
            rows.sort(key=lambda i: i["received"], reverse=True)
        return rows, facets

    def estimate(self) -> dict:
        items = min(len(self.queue()), self.budget["items_per_run"])
        return {"items": items, "cost": round(items * 0.1, 2)}

    # --- writes ------------------------------------------------------------------
    def review(self, item_id: str, decision: str, note: str, actor: str) -> dict:
        item = self.find(item_id)
        if item is None:
            raise LookupError(f"No submission {item_id}")
        if decision not in DECISIONS:
            raise ValueError("decision must be approve, hold, reject or reopen")
        item["status"] = DECISIONS[decision]
        item["reviewed_by"] = None if decision == "reopen" else actor
        if note.strip():
            item["note"] = note.strip()
        verb = {"approve": "approved", "hold": "held", "reject": "rejected", "reopen": "reopened"}[decision]
        self._log(datetime.now(timezone.utc), actor, verb, item["id"], item["title"])
        return item

    def set_budget(self, dollars: float, items: int, actor: str = "unknown") -> dict:
        if not (0 < dollars <= 1000) or not (0 < items <= 10000):
            raise ValueError("Budget must be between $0 and $1,000 and 1 to 10,000 submissions")
        self.budget = {"dollars_per_run": float(dollars), "items_per_run": int(items)}
        self._log(datetime.now(timezone.utc), actor, "changed", "budget",
                  f"${dollars:g} and {items} submissions per run")
        return self.budget

    def start_run(self, actor: str) -> dict:
        estimate = self.estimate()
        if estimate["cost"] > self.budget["dollars_per_run"]:
            raise ValueError("The estimated cost is over the per-run budget")
        run = {"id": f"RUN-{len(self.runs) + 1:03d}", "started": self._now.isoformat(timespec="minutes"),
               "status": "running", "items": estimate["items"], "cost": estimate["cost"], "started_by": actor}
        self.runs.append(run)
        self._log(datetime.now(timezone.utc), actor, "started", run["id"], f"{run['items']} submissions")
        return run

    def _log(self, at: datetime, actor: str, verb: str, target: str, title: str) -> None:
        self.activity.append({"seq": len(self.activity) + 1, "at": at.isoformat(timespec="minutes"), "actor": actor,
                              "verb": verb, "target": target, "title": title})


def _tally(values) -> dict:
    out: dict[str, int] = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items()))
