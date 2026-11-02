"""MySQL adapter for production deployments.

Install the optional dependency with ``pip install -r requirements-mysql.txt``.
The adapter implements the same ``Database`` contract as the SQLite adapter and
expects the tables in ``schema/schema.mysql.sql``.  MySQL 8.0.16 or newer is
recommended because earlier releases parse but do not enforce CHECK constraints.
"""

from __future__ import annotations

import json
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

try:  # optional dependency: importing this module must work without PyMySQL
    import pymysql
    from pymysql.cursors import DictCursor
except ImportError:  # pragma: no cover - exercised when PyMySQL is absent
    pymysql = None
    DictCursor = None

from ..errors import DatabaseIntegrityError
from .base import (
    REFERENCE_TABLE_PK,
    TABLE_PK,
    build_insert_sql,
    quote_identifier,
)

DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "schema.mysql.sql"
_COMMENT_RE = re.compile(r"(?m)^\s*--.*$")


class MySQLDatabase:
    """Database facade backed by a PyMySQL connection."""

    dialect = "mysql"

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 3306,
        user: str,
        password: str = "",
        database: str,
        charset: str = "utf8mb4",
        connect_timeout: int = 10,
        schema_path: str | Path | None = None,
        init_schema: bool = False,
    ):
        if pymysql is None:  # pragma: no cover - depends on environment
            raise RuntimeError(
                "MySQL support requires PyMySQL: pip install -r requirements-mysql.txt"
            )
        self._lock = threading.RLock()
        self._depth = 0
        self._actor_user_id: int | None = None
        self._closed = False
        self._connection = pymysql.connect(
            host=host,
            port=int(port),
            user=user,
            password=password,
            database=database,
            charset=charset,
            connect_timeout=connect_timeout,
            autocommit=True,
            cursorclass=DictCursor,
        )
        try:
            # Store naive timestamps consistently in UTC, matching utcnow().
            self._command("SET time_zone = '+00:00'")
            if init_schema:
                schema_file = Path(schema_path) if schema_path else DEFAULT_SCHEMA_PATH
                self._run_schema(schema_file.read_text(encoding="utf-8"))
        except BaseException:
            self.close()
            raise

    # ------------------------------------------------------------------ core
    def _cursor_locked(self, sql: str, params: Any = ()):
        cursor = self._connection.cursor()
        cursor.execute(sql, tuple(params or ()))
        return cursor

    def _command(self, sql: str) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(sql)

    def _run_schema(self, script: str) -> None:
        script = _COMMENT_RE.sub("", script)
        for statement in script.split(";"):
            statement = statement.strip()
            if statement:
                self._command(statement)

    @staticmethod
    def _normalise_integrity_error(exc) -> DatabaseIntegrityError:
        text = str(exc)
        constraint = ""

        match = re.search(r"for key '([^']+)'", text, re.IGNORECASE)
        if match:
            constraint = match.group(1).rsplit(".", 1)[-1]
        if not constraint:
            match = re.search(r"CONSTRAINT [`']([^`']+)[`']", text, re.IGNORECASE)
            if match:
                constraint = match.group(1)
        if not constraint:
            match = re.search(
                r"Check constraint '([^']+)' is violated", text, re.IGNORECASE
            )
            if match:
                constraint = match.group(1)
        if not constraint:
            match = re.search(r"Column '([^']+)' cannot be null", text, re.IGNORECASE)
            if match:
                constraint = f"nn_unknown_{match.group(1)}"
        if not constraint and exc.args and exc.args[0] == 1452:
            constraint = "fk_unknown"

        return DatabaseIntegrityError(text, constraint)

    def query_one(self, sql: str, params: Any = ()) -> dict | None:
        with self._lock:
            with self._cursor_locked(sql, params) as cursor:
                return cursor.fetchone()

    def query_all(self, sql: str, params: Any = ()) -> list[dict]:
        with self._lock:
            with self._cursor_locked(sql, params) as cursor:
                return list(cursor.fetchall())

    def execute(self, sql: str, params: Any = ()) -> int:
        with self._lock:
            try:
                with self._cursor_locked(sql, params) as cursor:
                    return cursor.rowcount
            except pymysql.err.IntegrityError as exc:  # pragma: no cover
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
                    return int(cursor.lastrowid or cursor.rowcount or 0)
            except pymysql.err.IntegrityError as exc:  # pragma: no cover
                raise self._normalise_integrity_error(exc) from exc

    def insert_returning_id(self, table: str, data: dict) -> int:
        if not isinstance(data, dict) or not data:
            raise ValueError("insert requires a non-empty dict")
        primary_key = TABLE_PK.get(table)
        if primary_key is None:
            raise ValueError(f"table {table!r} has no single-column primary key")
        sql = build_insert_sql(table, list(data.keys()))
        with self._lock:
            try:
                with self._cursor_locked(sql, list(data.values())) as cursor:
                    generated_id = int(cursor.lastrowid or 0)
            except pymysql.err.IntegrityError as exc:  # pragma: no cover
                raise self._normalise_integrity_error(exc) from exc
        if generated_id <= 0:
            raise RuntimeError(f"insert into {table!r} did not return an id")
        return generated_id

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
    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            outermost = self._depth == 0
            if outermost:
                self._command("START TRANSACTION")
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
        # Lets MySQL triggers or views read the acting user for audit/RLS-style rules.
        self.execute("SET @internlink_actor_user_id = %s", [self._actor_user_id])

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

    def __enter__(self) -> "MySQLDatabase":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self):  # pragma: no cover - defensive cleanup for short-lived tools
        try:
            self.close()
        except Exception:
            pass
