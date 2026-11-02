"""Ports (interfaces) for services owned by other modules.

The employer module depends on these small contracts instead of concrete
mailers, storage, caches or auth services.  Production swaps in the real
implementations; tests use the reference adapters in ``adapters.py``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AuthService(Protocol):
    def verify_token(self, token: str | None) -> dict | None:
        """Return claims containing an integer ``user_id`` for a valid token."""

        ...


@runtime_checkable
class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


@runtime_checkable
class Notifier(Protocol):
    def notify(
        self,
        user_id: int,
        type: str,
        title: str,
        message: str,
        related_type: str | None = None,
        related_id: int | None = None,
    ) -> None: ...


@runtime_checkable
class Storage(Protocol):
    def read_bytes(self, path: str) -> bytes: ...


@runtime_checkable
class MatchingCache(Protocol):
    def invalidate_all(self) -> None: ...
