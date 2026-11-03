"""
db.py - PostgreSQL connection pool and small query helpers.

Usage in other files:
    import db
    rows = db.fetch_all("SELECT * FROM skills ORDER BY name")
    row  = db.fetch_one("SELECT * FROM users WHERE user_id = %s", (5,))

    with db.transaction(user_id=5) as cur:      # several statements, one commit
        cur.execute("INSERT ...", (...))
        cur.execute("INSERT ...", (...))

Passing user_id sets app.user_id for the transaction, which your schema
says is used by the audit log (audit_logs.actor_user_id).
"""
from contextlib import contextmanager

from psycopg2 import pool
from psycopg2.extras import RealDictCursor

import config

_pool = None


def init_pool() -> None:
    """Create the connection pool once."""
    global _pool
    if _pool is None:
        _pool = pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=config.DATABASE_URL)


@contextmanager
def transaction(user_id=None):
    """
    Give a cursor that returns rows as dictionaries.
    Commits when the block ends normally, rolls back if an error is raised.
    """
    init_pool()
    conn = _pool.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if user_id is not None:
                cur.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


def fetch_all(sql, params=None, user_id=None):
    """Run a SELECT and return a list of dictionaries."""
    with transaction(user_id) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def fetch_one(sql, params=None, user_id=None):
    """Run a SELECT and return one dictionary, or None if there is no row."""
    with transaction(user_id) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None


def execute(sql, params=None, user_id=None):
    """Run an INSERT/UPDATE/DELETE and return the number of rows affected."""
    with transaction(user_id) as cur:
        cur.execute(sql, params)
        return cur.rowcount


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


# Quick connection test:  python db.py
if __name__ == "__main__":
    try:
        row = fetch_one(
            "SELECT "
            "(SELECT count(*) FROM universities WHERE status = 'verified') AS verified_universities, "
            "(SELECT count(*) FROM programmes) AS programmes, "
            "(SELECT count(*) FROM skills) AS skills, "
            "(SELECT count(*) FROM listings WHERE status = 'open') AS open_listings"
        )
        print("Database connection OK")
        for key, value in row.items():
            print(f"  {key}: {value}")
    except Exception as exc:
        print("Database connection FAILED:")
        print(" ", exc)
    finally:
        close_pool()