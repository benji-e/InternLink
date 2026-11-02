"""Small stdlib adapters that make the module runnable without other services.

These are suitable for local development and tests.  Production should inject
the implementations owned by the notifications/matching/storage modules.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ConsoleMailer:
    """Prints outgoing mail instead of sending it (development only)."""

    def send(self, to: str, subject: str, body: str) -> None:
        logger.info("mail to=%s subject=%r body=%r", to, subject, body)


class MemoryMailer:
    """Records messages in memory; useful for tests and local demos."""

    def __init__(self):
        self.sent: list[dict] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append({"to": to, "subject": subject, "body": body})


class MemoryNotifier:
    """Records notifications without requiring the notifications module."""

    def __init__(self):
        self.sent: list[dict] = []

    def notify(
        self,
        user_id: int,
        type: str,
        title: str,
        message: str,
        related_type: str | None = None,
        related_id: int | None = None,
    ) -> None:
        self.sent.append(
            {
                "user_id": user_id,
                "type": type,
                "title": title,
                "message": message,
                "related_type": related_type,
                "related_id": related_id,
            }
        )


class MemoryStorage:
    """In-memory object store keyed by relative path."""

    def __init__(self, files: dict[str, bytes] | None = None):
        self.files = dict(files or {})

    def read_bytes(self, path: str) -> bytes:
        try:
            return self.files[path]
        except KeyError as exc:
            raise FileNotFoundError(path) from exc


class LocalFileStorage:
    """Read-only access to a private directory outside the web root.

    Every path is resolved and checked against the configured root, so a
    malicious ``cv_path`` cannot escape the CV folder.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    def read_bytes(self, path: str) -> bytes:
        candidate = (self.root / str(path)).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise PermissionError("storage path escapes the configured root")
        return candidate.read_bytes()


class NoopMatchingCache:
    """Adapter used when the recommendation cache is not wired in yet."""

    def invalidate_all(self) -> None:
        return None


class MemoryMatchingCache:
    """Tracks invalidation calls for diagnostics and tests."""

    def __init__(self):
        self.invalidations = 0

    def invalidate_all(self) -> None:
        self.invalidations += 1
