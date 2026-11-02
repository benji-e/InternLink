"""Local development entry point.

    python run.py                 # http://127.0.0.1:8080
    python run.py --port 9000

The SQLite database and CV folder are created under ./data.  Set
INTERNLINK_TOKEN_SECRET to keep bearer tokens valid across restarts.
"""

from __future__ import annotations

import argparse
import logging
import os
import secrets
from pathlib import Path

from internlink_employer.adapters import ConsoleMailer, LocalFileStorage, MemoryNotifier
from internlink_employer.api import EmployerAPI
from internlink_employer.context import AppContext
from internlink_employer.db import SQLiteDatabase
from internlink_employer.security import ReferenceTokenService

BASE_DIR = Path(__file__).resolve().parent


def build_context(
    *,
    db_path: Path,
    secret: str,
    cv_root: Path,
    base_url: str,
) -> AppContext:
    db = SQLiteDatabase(db_path)
    return AppContext(
        db=db,
        auth=ReferenceTokenService(secret),
        mailer=ConsoleMailer(),
        notifier=MemoryNotifier(),
        storage=LocalFileStorage(cv_root),
        base_url=base_url,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="InternLink employer module (development)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--db", default=str(BASE_DIR / "data" / "internlink.db"), help="SQLite database file"
    )
    parser.add_argument(
        "--cv-root", default=str(BASE_DIR / "data" / "cvs"), help="private CV folder"
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="public base URL used in verification links (defaults to host:port)",
    )
    args = parser.parse_args()
    base_url = args.base_url or f"http://{args.host}:{args.port}"

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    secret = os.environ.get("INTERNLINK_TOKEN_SECRET", "")
    if not secret:
        secret = secrets.token_urlsafe(48)
        logging.warning(
            "INTERNLINK_TOKEN_SECRET is not set; using an ephemeral development secret"
        )

    Path(args.cv_root).mkdir(parents=True, exist_ok=True)
    ctx = build_context(
        db_path=Path(args.db),
        secret=secret,
        cv_root=Path(args.cv_root),
        base_url=base_url,
    )
    api = EmployerAPI(ctx)

    from wsgiref.simple_server import make_server

    with make_server(args.host, args.port, api) as server:
        logging.info("Employer API listening on http://%s:%s", args.host, args.port)
        logging.info(
            "POST /api/employer/register, /api/employer/verify-email, /api/employer/<action>"
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            logging.info("Shutting down")
        finally:
            ctx.db.close()


if __name__ == "__main__":
    main()
