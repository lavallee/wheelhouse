"""In-process memory of command results, keyed by Idempotency-Key.

One store belongs to one ``Admin``. It does not survive a restart and is not
shared between worker processes.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Hashable

TTL_SECONDS = 24 * 3600

RUN = "run"            # first sight of the key: run the handler
REPLAY = "replay"      # finished before: send the stored result
BUSY = "busy"          # the first request with this key is still running
MISMATCH = "mismatch"  # the key was used before with a different body


@dataclass
class _Entry:
    at: float
    fingerprint: str
    status: int | None = None   # None while the handler is running
    body: bytes | None = None


class IdempotencyStore:
    def __init__(self, ttl: float = TTL_SECONDS) -> None:
        self.ttl = ttl
        self._now = time.monotonic
        self._entries: dict[Hashable, _Entry] = {}
        self._lock = threading.Lock()

    def begin(self, key: Hashable, fingerprint: str) -> tuple[str, tuple[int, bytes] | None]:
        """Claim ``key``. Returns ``(RUN | REPLAY | BUSY | MISMATCH, stored result)``."""
        now = self._now()
        with self._lock:
            for stale in [k for k, e in self._entries.items() if now - e.at > self.ttl]:
                del self._entries[stale]
            entry = self._entries.get(key)
            if entry is None:
                self._entries[key] = _Entry(now, fingerprint)
                return RUN, None
            if entry.fingerprint != fingerprint:
                return MISMATCH, None
            if entry.status is None or entry.body is None:
                return BUSY, None
            return REPLAY, (entry.status, entry.body)

    def finish(self, key: Hashable, status: int, body: bytes) -> None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                entry.status, entry.body = status, body

    def abandon(self, key: Hashable) -> None:
        """The handler failed: forget the claim so the same key can be retried."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.status is None:
                del self._entries[key]

    def __len__(self) -> int:
        return len(self._entries)
