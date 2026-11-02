"""PostgreSQL adapter for the shared InternLink database."""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from ..errors import DatabaseIntegrityError
from .base import REFERENCE_TABLE_PK, TABLE_PK


class PostgresDatabase:
    """Implements the employer service database contract on PostgreSQL."""

    dialect = "postgresql"

    def __init__(self, pool: ConnectionPool):
        self._pool = pool
        self._connection = pool.getconn(timeout=5)
        self._connection.autocommit = True
        self._closed = False
        self._actor_user_id: int | None = None

    @staticmethod
    def _integrity_error(error: psycopg.IntegrityError) -> DatabaseIntegrityError:
        diagnostic = error.diag
        return DatabaseIntegrityError(
            str(error),
            getattr(diagnostic, "constraint_name", None),
        )

    def query_one(self, sql: str, params: Any = ()) -> dict | None:
        try:
            with self._connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(sql.replace("decided_at", "status_changed_at"), tuple(params or ()))
                return cursor.fetchone()
        except psycopg.IntegrityError as error:
            raise self._integrity_error(error) from error

    def query_all(self, sql: str, params: Any = ()) -> list[dict]:
        try:
            with self._connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(sql.replace("decided_at", "status_changed_at"), tuple(params or ()))
                return list(cursor.fetchall())
        except psycopg.IntegrityError as error:
            raise self._integrity_error(error) from error

    def execute(self, sql: str, params: Any = ()) -> int:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(sql.replace("decided_at", "status_changed_at"), tuple(params or ()))
                return cursor.rowcount
        except psycopg.IntegrityError as error:
            raise self._integrity_error(error) from error

    def _insert(self, table: str, data: dict, returning: str | None = None) -> int:
        if not isinstance(data, dict) or not data:
            raise ValueError("insert requires a non-empty dict")
        if not table.replace("_", "").isalnum() or not table[0].isalpha():
            raise ValueError("unsafe table name")
        if not all(column.replace("_", "").isalnum() and column[0].isalpha() for column in data):
            raise ValueError("unsafe column name")

        values = dict(data)
        if table == "notifications" and values.get("channel") == "in_app":
            values["delivery_status"] = "sent"
            values["sent_at"] = "now()"
        columns = list(values)
        expressions = ["now()" if value == "now()" else "%s" for value in values.values()]
        params = [value for value in values.values() if value != "now()"]
        sql = (
            f"INSERT INTO {table} ({', '.join(columns)}) "
            f"VALUES ({', '.join(expressions)})"
        )
        if returning:
            sql += f" RETURNING {returning}"
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(sql, params)
                if returning:
                    row = cursor.fetchone()
                    if row is None:
                        raise RuntimeError(f"insert into {table!r} did not return an id")
                    return int(row[0])
                return cursor.rowcount
        except psycopg.IntegrityError as error:
            raise self._integrity_error(error) from error

    def insert(self, table: str, data: dict) -> int:
        if table in TABLE_PK:
            return self.insert_returning_id(table, data)
        return self._insert(table, data)

    def insert_returning_id(self, table: str, data: dict) -> int:
        primary_key = TABLE_PK.get(table)
        if primary_key is None:
            raise ValueError(f"table {table!r} has no single-column primary key")
        if table == "audit_log":
            raise ValueError("audit events must use log_event")
        return self._insert(table, data, primary_key)

    def count_existing(self, table: str, ids: list[int]) -> int:
        primary_key = REFERENCE_TABLE_PK.get(table)
        if primary_key is None:
            raise ValueError(f"table {table!r} is not a controlled vocabulary")
        unique_ids = sorted({int(value) for value in ids})
        if any(value <= 0 for value in unique_ids):
            raise ValueError("ids must be positive")
        if not unique_ids:
            return 0
        row = self.query_one(
            f"SELECT count(*) AS n FROM {table} WHERE {primary_key} = ANY(%s)",
            (unique_ids,),
        )
        return int(row["n"]) if row else 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        try:
            with self._connection.transaction():
                yield
        except psycopg.IntegrityError as error:
            raise self._integrity_error(error) from error

    def set_actor(self, user_id: int | None) -> None:
        self._actor_user_id = int(user_id) if user_id is not None else None
        self._connection.execute(
            "SELECT set_config('app.user_id', %s, false)",
            ("" if user_id is None else str(int(user_id)),),
        )

    def log_event(
        self,
        action: str,
        entity_type: str | None = None,
        entity_id: str | int | None = None,
        result: str | None = None,
        details: dict | None = None,
    ) -> None:
        self._connection.execute(
            "SELECT log_event(%s, %s, %s, %s, %s::jsonb)",
            (
                action,
                entity_type,
                None if entity_id is None else str(entity_id),
                result or "success",
                json.dumps(details or {}, separators=(",", ":"), default=str),
            ),
        )

    def close(self) -> None:
        if not self._closed:
            self.set_actor(None)
            self._pool.putconn(self._connection)
            self._closed = True
