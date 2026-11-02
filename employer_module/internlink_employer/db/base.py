"""Database port and small SQL-building helpers shared by the adapters."""

from __future__ import annotations

import re
from contextlib import AbstractContextManager
from typing import Any, Protocol

_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

# Only tables with a single surrogate primary key can use insert_returning_id.
TABLE_PK = {
    "companies": "company_id",
    "users": "user_id",
    "auth_tokens": "token_id",
    "student_profiles": "student_id",
    "listings": "listing_id",
    "applications": "application_id",
    "placements": "placement_id",
    "messages": "message_id",
    "notifications": "notification_id",
    "audit_log": "event_id",
}

# Tables used by the controlled vocabulary check in listing validation.
REFERENCE_TABLE_PK = {
    "skills": "skill_id",
    "programmes": "programme_id",
    "interests": "interest_id",
}


def quote_identifier(value: str) -> str:
    """Validate and quote a SQL identifier that originates in our own code.

    Backticks are accepted by both SQLite and MySQL; this keeps the adapter
    independent of MySQL's ``ANSI_QUOTES`` SQL mode.
    """

    if not isinstance(value, str) or not _IDENTIFIER_RE.match(value):
        raise ValueError(f"unsafe SQL identifier: {value!r}")
    return f"`{value}`"


def build_insert_sql(table: str, columns: list[str], returning: str | None = None) -> str:
    quoted_table = quote_identifier(table)
    quoted_columns = ", ".join(quote_identifier(column) for column in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    sql = f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({placeholders})"
    if returning:
        sql += f" RETURNING {quote_identifier(returning)}"
    return sql


class Database(Protocol):
    """The persistence contract used by the service layer.

    SQL uses ``%s`` placeholders.  The SQLite adapter translates them to
    ``?``; the MySQL adapter passes them straight to PyMySQL.
    """

    def query_one(self, sql: str, params: Any = ()) -> dict | None: ...

    def query_all(self, sql: str, params: Any = ()) -> list[dict]: ...

    def execute(self, sql: str, params: Any = ()) -> int: ...

    def insert(self, table: str, data: dict) -> int: ...

    def insert_returning_id(self, table: str, data: dict) -> int: ...

    def count_existing(self, table: str, ids: list[int]) -> int: ...

    def transaction(self) -> AbstractContextManager: ...

    def set_actor(self, user_id: int | None) -> None: ...

    def log_event(
        self,
        action: str,
        entity_type: str | None = None,
        entity_id: str | int | None = None,
        result: str | None = None,
        details: dict | None = None,
    ) -> None: ...

    def close(self) -> None: ...
