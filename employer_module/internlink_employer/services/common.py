"""Helpers shared by the employer service modules."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Any, Callable, TypeVar

from ..errors import DatabaseIntegrityError, ModuleError, translate_db_error
from ..session import Session

T = TypeVar("T")

logger = logging.getLogger(__name__)

_INTEGER_RE = re.compile(r"^[+-]?\d+$")


def _coerce_int(value: Any) -> int | None:
    """Strict integer coercion shared by ids and pagination."""

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        text = value.strip()
        if not _INTEGER_RE.match(text):
            return None
        return int(text)
    return None


def utcnow() -> datetime:
    """Naive UTC timestamp, stored consistently by both database adapters."""

    return datetime.now(timezone.utc).replace(tzinfo=None)


def today() -> date:
    return date.today()


def as_id(value: Any, label: str = "id") -> int:
    number = _coerce_int(value)
    if number is None or number <= 0:
        raise ModuleError("invalid", f"Invalid {label}.", {label: "Invalid"})
    return number


def as_page(value: Any) -> int:
    if value is None or value == "":
        return 1
    page = _coerce_int(value)
    if page is None or page < 1:
        raise ModuleError("invalid", "Page must be a positive whole number.", {"page": "Invalid"})
    return page


def as_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"0", "false", "no", "off"}:
            return False
        if lowered in {"1", "true", "yes", "on"}:
            return True
        return default
    return bool(value)


def as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def run_write(db, session: Session, action: Callable[[], T]) -> T:
    """Run one write in a transaction, tell the DB who is acting, translate rules."""

    try:
        with db.transaction():
            db.set_actor(session.user_id)
            return action()
    except DatabaseIntegrityError as err:
        try:
            # Audit after the rollback; a broken audit sink must not hide the rule error.
            db.set_actor(session.user_id)
            db.log_event(
                "rule_violation",
                details={
                    "code": (err.message or "").split(":", 1)[0],
                    "constraint": err.constraint_name,
                },
            )
        except Exception:
            logger.exception("Could not write the rule-violation audit row")
        raise translate_db_error(err) from err
    finally:
        db.set_actor(None)


def own_listing(db, session: Session, listing_id: int) -> dict:
    """Load a listing only when it belongs to the session's company (SR17/NFR06)."""

    listing_id = as_id(listing_id, "listing_id")
    row = db.query_one(
        "SELECT * FROM listings WHERE listing_id = %s AND company_id = %s",
        [listing_id, session.company_id],
    )
    if row is None:
        # Deliberately 404 rather than 403 so other companies' records stay hidden.
        raise ModuleError("not_found", "Listing not found.")
    return row


def own_application(db, session: Session, application_id: int) -> dict:
    application_id = as_id(application_id, "application_id")
    row = db.query_one(
        """
        SELECT a.*, l.company_id, l.title, l.slots, l.slots_filled
        FROM applications a
        JOIN listings l ON l.listing_id = a.listing_id
        WHERE a.application_id = %s AND l.company_id = %s
        """,
        [application_id, session.company_id],
    )
    if row is None:
        raise ModuleError("not_found", "Application not found.")
    return row


def notify_user(
    db,
    user_id: int,
    notification_type: str,
    title: str,
    message: str,
    related_type: str | None = None,
    related_id: int | None = None,
) -> None:
    """Write an in-app notification; the notifications module may also email."""

    db.insert(
        "notifications",
        {
            "user_id": int(user_id),
            "type": notification_type,
            "title": title,
            "message": message,
            "channel": "in_app",
            "related_type": related_type,
            "related_id": related_id,
            "is_read": False,
        },
    )


def student_user_id(db, student_id: int) -> int | None:
    row = db.query_one(
        "SELECT user_id FROM student_profiles WHERE student_id = %s", [student_id]
    )
    return int(row["user_id"]) if row else None


def active_placement_count(db, listing_id: int) -> int:
    """Pending + confirmed placements occupy a slot; completed ones do not."""

    row = db.query_one(
        """
        SELECT count(*) AS n
        FROM placements p
        JOIN applications a ON a.application_id = p.application_id
        WHERE a.listing_id = %s AND p.status IN ('pending', 'confirmed')
        """,
        [listing_id],
    )
    return int(row["n"]) if row else 0


def recount_slots(db, listing_id: int) -> None:
    db.execute(
        """
        UPDATE listings
        SET slots_filled = (
            SELECT count(*)
            FROM placements p
            JOIN applications a ON a.application_id = p.application_id
            WHERE a.listing_id = listings.listing_id
              AND p.status IN ('pending', 'confirmed')
        )
        WHERE listing_id = %s
        """,
        [listing_id],
    )


def lock_listing_for_update(db, listing_id: int) -> None:
    """Serialise capacity decisions on MySQL; SQLite serialises writers."""

    if getattr(db, "dialect", "sqlite") == "mysql":
        db.query_one(
            "SELECT listing_id FROM listings WHERE listing_id = %s FOR UPDATE",
            [listing_id],
        )


def lock_application_for_update(db, application_id: int) -> None:
    """Serialise message sending against a concurrent decision (SR10)."""

    if getattr(db, "dialect", "sqlite") == "mysql":
        db.query_one(
            "SELECT application_id FROM applications WHERE application_id = %s FOR UPDATE",
            [application_id],
        )
