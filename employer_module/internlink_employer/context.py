"""Application context shared by the service, handler and WSGI layers."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .adapters import NoopMatchingCache
from .db.base import Database
from .ports import AuthService, Mailer, MatchingCache, Notifier, Storage
from .session import Session


@dataclass(frozen=True)
class AppContext:
    db: Database
    auth: AuthService
    mailer: Mailer
    notifier: Notifier
    storage: Storage
    cache: MatchingCache = field(default_factory=NoopMatchingCache)
    base_url: str = "http://localhost:8000"
    session: Session | None = None

    def with_session(self, session: Session) -> "AppContext":
        """Return a per-request copy instead of mutating shared state."""

        return replace(self, session=session)
