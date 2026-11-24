"""Errors a handler raises to answer with ``{"error": message}`` and a status."""
from __future__ import annotations


class AdminError(Exception):
    """Raise from a handler to send ``{"error": message}`` with ``status``."""

    status = 400

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        if status is not None:
            self.status = status


class NotFound(AdminError):
    status = 404


class Conflict(AdminError):
    status = 409


class Invalid(AdminError):
    status = 422
