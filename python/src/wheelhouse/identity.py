"""Who is asking: the identity a provider reads from a request.

A provider is a callable ``(request) -> Identity | None`` (sync or async).
``None`` means nobody is signed in (401). It may raise ``AdminError`` to refuse
with its own message and status. It decides only *who*; the ``Admin`` still
checks ``allowed_groups`` and runs the same command guard under every provider.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from starlette.requests import Request


@dataclass(frozen=True)
class Identity:
    """An actor (``human:ada``), the groups they hold, and a name to show."""

    actor: str
    groups: frozenset[str] = field(default_factory=frozenset)
    display_name: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.actor, str):
            raise TypeError("actor must be a string")
        object.__setattr__(self, "actor", self.actor.strip())
        if isinstance(self.groups, str):
            raise TypeError("groups must be a collection of names, not a string")
        object.__setattr__(self, "groups", frozenset(self.groups))
        name = self.display_name.strip() if isinstance(self.display_name, str) else None
        object.__setattr__(self, "display_name", name or None)


class ProxyHeaders:
    """The sign-in proxy's headers: a uid, separated groups, optionally a name.

    The default provider is ``ProxyHeaders()``: ``x-authentik-uid`` and
    pipe-separated ``x-authentik-groups``, no name. These headers are trusted as
    sent, so the app must be reachable only through a proxy that strips any
    copy a client supplies, including the name header if one is read.
    """

    auth = "authentik"

    def __init__(self, uid: str = "x-authentik-uid", groups: str = "x-authentik-groups",
                 name: str | None = None, separator: str = "|") -> None:
        if not separator:
            raise ValueError("separator must be a non-empty string")
        self.uid, self.groups, self.name, self.separator = uid, groups, name, separator

    def __call__(self, request: Request) -> Identity | None:
        actor = request.headers.get(self.uid, "").strip()
        if not actor:
            return None
        raw = request.headers.get(self.groups, "")
        groups: Iterable[str] = (g.strip() for g in raw.split(self.separator) if g.strip())
        name = request.headers.get(self.name, "") if self.name else ""
        return Identity(actor, frozenset(groups), name or None)


def proxy_headers(uid: str = "x-authentik-uid", groups: str = "x-authentik-groups",
                  name: str | None = None, separator: str = "|") -> ProxyHeaders:
    """A provider that reads the sign-in proxy's headers; see ``ProxyHeaders``."""
    return ProxyHeaders(uid, groups, name, separator)
