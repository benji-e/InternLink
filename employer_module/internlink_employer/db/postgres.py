"""PostgreSQL adapter for production deployments.

Install the optional dependency with ``pip install "psycopg[binary]"``.  The
adapter is intentionally thin and implements the same ``Database`` contract as
the SQLite adapter.  See ``schema/schema.postgres.sql`` for the expected tables.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

try:  # optional dependency: importing the module must work without psycopg
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - exercised when psycopg is absent
    psycopg = None
    dict_row = None

from ..errors import DatabaseIntegrityError
from .base import (
    REFERENCE_TABLE_PK,
    TABLE_PK,
    build_insert_sql,
    quote_identifier,
)

DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "schema.postgres.sql"


class PostgresDatabase:
    """Database facade backed by a psycopg 3 connection."""

    dialect = "postgres"

    def __init__(
        self,
        dsn: str,
        *,
        schema_path: str | Path | None = None,
        init_schema: bool = False,
    ):
        if psycopg is None:  # pragma: no cover - depends on environment
            raise RuntimeError(
                "PostgreSQL support requires psycopg 3: pip install 'psycopg[binary]'"
            )
        self._lock = threading.RLock()
        self._depth = 0
        self._actor_user_id: int | None = None
        self._closed = False
        self._connection = psycopg.connect(dsn, autocommit=True)
        if init_schema:
            schema_file = Path(schema_path) if schema_path else DEFAULT_SCHEMA_PATH
            with self._connection.cursor() as cursor:
                cursor.execute(schema_file.read_text(encoding="utf-8"))

    def _cursor_locked(self, sql: str, params: Any = ()):
        cursor = self._connection.cursor(row_factory=dict_row)
        cursor.execute(sql, tuple(params or ()))
        return cursor

    @staticmethod
    def _normalise_integrity_error(exc) -> DatabaseIntegrityError:
        constraint = ""
        diag = getattr(exc, "diag", None)
        if diag is not None:
            constraint = getattr(diag, "constraint_name", None) or ""
        return DatabaseIntegrityError(str(exc), constraint)

    # ------------------------------------------------------------------ core
    def query_one(self, sql: str, params: Any = ()) -> dict | None:
        with self._lock:
            with self._cursor_locked(sql, params) as cursor:
                return cursor.fetchone()

    def query_all(self, sql: str, params: Any = ()) -> list[dict]:
        with self._lock:
            with self._cursor_locked(sql, params) as cursor:
                return cursor.fetchall()

    def execute(self, sql: str, params: Any = ()) -> int:
        with self._lock:
            try:
                with self._cursor_locked(sql, params) as cursor:
                    return cursor.rowcount
            except psycopg.errors.IntegrityError as exc:  # pragma: no cover
                raise self._normalise_integrity_error(exc) from exc

    def insert(self, table: str, data: dict) -> int:
        if not isinstance(data, dict) or not data:
            raise ValueError("insert requires a non-empty dict")
        if table in TABLE_PK:
            return self.insert_returning_id(table, data)
        sql = build_insert_sql(table, list(data.keys()))
        with self._lock:
            try:
                with self._cursor_locked(sql, list(data.values())) as cursor:
                    return int(cursor.rowcount)
            except psycopg.errors.IntegrityError as exc:  # pragma: no cover
                raise self._normalise_integrity_error(exc) from exc

    def insert_returning_id(self, table: str, data: dict) -> int:
        if not isinstance(data, dict) or not data:
            raise ValueError("insert requires a non-empty dict")
        primary_key = TABLE_PK.get(table)
        if primary_key is None:
            raise ValueError(f"table {table!r} has no single-column primary key")
        sql = build_insert_sql(table, list(data.keys()), returning=primary_key)
        with self._lock:
            try:
                with self._cursor_locked(sql, list(data.values())) as cursor:
                    row = cursor.fetchone()
            except psycopg.errors.IntegrityError as exc:  # pragma: no cover
                raise self._normalise_integrity_error(exc) from exc
        if row is None:
            raise RuntimeError(f"insert into {table!r} did not return an id")
        return int(row[primary_key])

    def count_existing(self, table: str, ids: list[int]) -> int:
        primary_key = REFERENCE_TABLE_PK.get(table)
        if primary_key is None:
            raise ValueError(f"table {table!r} is not a controlled vocabulary")
        unique_ids = sorted({int(value) for value in ids})
        if any(value <= 0 for value in unique_ids):
            raise ValueError("ids must be positive")
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
    def _command(self, sql: str) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(sql)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            outermost = self._depth == 0
            if outermost:
                self._command("BEGIN")
            self._depth += 1
            try:
                yield
            except BaseException:
                self._depth -= 1
                if outermost:
                    self._command("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if outermost:
                    self._command("COMMIT")

    # ----------------------------------------------------------------- audit
    def set_actor(self, user_id: int | None) -> None:
        self._actor_user_id = int(user_id) if user_id is not None else None
        # Lets RLS policies or trigger functions read the acting user.
        self.execute("SELECT set_config('app.user_id', %s, true)", [str(self._actor_user_id or "")])

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

    def __enter__(self) -> "PostgresDatabase":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
