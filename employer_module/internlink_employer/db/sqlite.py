"""SQLite database adapter (stdlib only) used for tests and local development.

The service layer writes portable SQL with ``%s`` placeholders.  This adapter
translates those placeholders for SQLite and handles the few dialect details
(integrity-error parsing, date adapters, RETURNING support).
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

from ..errors import DatabaseIntegrityError
from .base import (
    REFERENCE_TABLE_PK,
    TABLE_PK,
    build_insert_sql,
    quote_identifier,
)

DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "schema.sqlite.sql"

# Python 3.12+ deprecates the implicit sqlite3 date/datetime adapters.  Register
# explicit ISO adapters so behaviour stays stable across versions.
sqlite3.register_adapter(date, lambda value: value.isoformat())
sqlite3.register_adapter(datetime, lambda value: value.isoformat(sep=" "))


class SQLiteDatabase:
    """Small synchronous database facade with explicit transaction control."""

    dialect = "sqlite"

    def __init__(
        self,
        path: str | Path = ":memory:",
        *,
        schema_path: str | Path | None = None,
        init_schema: bool = True,
    ):
        self.path = str(path)
        if self.path != ":memory:" and not self.path.startswith("file:"):
            parent = Path(self.path).expanduser().resolve().parent
            parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()
        self._depth = 0
        self._actor_user_id: int | None = None
        self._closed = False
        self._connection = sqlite3.connect(
            self.path,
            timeout=30,
            isolation_level=None,  # we manage BEGIN/COMMIT explicitly
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 30000")
        if self.path != ":memory:" and not self.path.startswith("file:"):
            self._connection.execute("PRAGMA journal_mode = WAL")

        if init_schema:
            schema_file = Path(schema_path) if schema_path else DEFAULT_SCHEMA_PATH
            schema_sql = schema_file.read_text(encoding="utf-8")
            self._connection.executescript(schema_sql)

    # ------------------------------------------------------------------ core
    @staticmethod
    def _translate(sql: str) -> str:
        # Our SQL never contains a literal "%s"; all values are parameterised.
        return sql.replace("%s", "?")

    def _cursor_locked(self, sql: str, params: Any):
        if isinstance(params, dict):
            return self._connection.execute(self._translate(sql), params)
        return self._connection.execute(self._translate(sql), tuple(params or ()))

    def _normalise_integrity_error(self, exc: sqlite3.IntegrityError) -> DatabaseIntegrityError:
        text = str(exc)
        constraint = ""

        match = re.search(r"CHECK constraint failed:\s*(\w+)", text)
        if match:
            constraint = match.group(1)
        else:
            match = re.search(
                r"UNIQUE constraint failed:\s*([\w]+)\.([\w]+)", text
            )
            if match:
                constraint = f"uq_{match.group(1)}_{match.group(2)}"
            else:
                match = re.search(
                    r"NOT NULL constraint failed:\s*([\w]+)\.([\w]+)", text
                )
                if match:
                    constraint = f"nn_{match.group(1)}_{match.group(2)}"
                elif "FOREIGN KEY constraint failed" in text:
                    constraint = "fk_unknown"

        return DatabaseIntegrityError(text, constraint)

    def query_one(self, sql: str, params: Any = ()) -> dict | None:
        with self._lock:
            row = self._cursor_locked(sql, params).fetchone()
            return dict(row) if row is not None else None

    def query_all(self, sql: str, params: Any = ()) -> list[dict]:
        with self._lock:
            rows = self._cursor_locked(sql, params).fetchall()
            return [dict(row) for row in rows]

    def execute(self, sql: str, params: Any = ()) -> int:
        with self._lock:
            try:
                cursor = self._cursor_locked(sql, params)
            except sqlite3.IntegrityError as exc:
                raise self._normalise_integrity_error(exc) from exc
            return cursor.rowcount

    def insert(self, table: str, data: dict) -> int:
        if not isinstance(data, dict) or not data:
            raise ValueError("insert requires a non-empty dict")
        if table in TABLE_PK:
            return self.insert_returning_id(table, data)
        columns = list(data.keys())
        sql = build_insert_sql(table, columns)
        with self._lock:
            try:
                cursor = self._cursor_locked(sql, list(data.values()))
            except sqlite3.IntegrityError as exc:
                raise self._normalise_integrity_error(exc) from exc
            return int(cursor.lastrowid or 0)

    def insert_returning_id(self, table: str, data: dict) -> int:
        if not isinstance(data, dict) or not data:
            raise ValueError("insert requires a non-empty dict")
        primary_key = TABLE_PK.get(table)
        if primary_key is None:
            raise ValueError(f"table {table!r} has no single-column primary key")
        sql = build_insert_sql(table, list(data.keys()), returning=primary_key)
        with self._lock:
            try:
                row = self._cursor_locked(sql, list(data.values())).fetchone()
            except sqlite3.IntegrityError as exc:
                raise self._normalise_integrity_error(exc) from exc
        if row is None:
            raise RuntimeError(f"insert into {table!r} did not return an id")
        return int(row[0])

    def count_existing(self, table: str, ids: list[int]) -> int:
        primary_key = REFERENCE_TABLE_PK.get(table)
        if primary_key is None:
            raise ValueError(f"table {table!r} is not a controlled vocabulary")
        unique_ids: list[int] = []
        seen: set[int] = set()
        for value in ids:
            number = int(value)
            if number <= 0:
                raise ValueError("ids must be positive")
            if number not in seen:
                seen.add(number)
                unique_ids.append(number)
        if not unique_ids:
            return 0
        placeholders = ", ".join(["%s"] * len(unique_ids))
        sql = (
            f"SELECT count(*) AS n FROM {quote_identifier(table)} "
            f"WHERE {quote_identifier(primary_key)} IN ({placeholders})"
        )
        row = self.query_one(sql, unique_ids)
        return int(row["n"]) if row else 0

    # ------------------------------------------------------------ transaction
    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            outermost = self._depth == 0
            if outermost:
                self._connection.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield
            except BaseException:
                self._depth -= 1
                if outermost:
                    self._connection.rollback()
                raise
            else:
                self._depth -= 1
                if outermost:
                    self._connection.commit()

    # ----------------------------------------------------------------- audit
    def set_actor(self, user_id: int | None) -> None:
        self._actor_user_id = int(user_id) if user_id is not None else None

    def log_event(
        self,
        action: str,
        entity_type: str | None = None,
        entity_id: str | int | None = None,
        result: str | None = None,
        details: dict | None = None,
    ) -> None:
        self.insert(
            "audit_log",
            {
                "actor_user_id": self._actor_user_id,
                "action": action,
                "entity_type": entity_type,
                "entity_id": None if entity_id is None else str(entity_id),
                "result": result,
                "details": json.dumps(details or {}, separators=(",", ":"), default=str),
            },
        )

    # ---------------------------------------------------------------- lifecycle
    def close(self) -> None:
        if not self._closed:
            self._connection.close()
            self._closed = True

    def __enter__(self) -> "SQLiteDatabase":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self):  # pragma: no cover - defensive cleanup for short-lived tools
        try:
            self.close()
        except Exception:
            pass
