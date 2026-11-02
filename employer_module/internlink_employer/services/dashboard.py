"""Employer dashboard and in-app notifications."""

from __future__ import annotations

from ..errors import ModuleError
from ..session import Session
from .common import as_id, run_write
from .company import get_company_status


def _count(db, sql: str, params) -> int:
    row = db.query_one(sql, params)
    return int(row["n"]) if row else 0


def employer_dashboard(db, session: Session) -> dict:
    company_id = session.company_id
    return {
        "company_status": get_company_status(db, session)["company"]["verification_status"],
        "listings_by_status": [
            {"status": row["status"], "n": int(row["n"])}
            for row in db.query_all(
                "SELECT status, count(*) AS n FROM listings WHERE company_id = %s GROUP BY status",
                [company_id],
            )
        ],
        "new_applications": _count(
            db,
            "SELECT count(*) AS n FROM v_employer_applicants WHERE company_id = %s AND status = 'submitted'",
            [company_id],
        ),
        "shortlisted": _count(
            db,
            "SELECT count(*) AS n FROM v_employer_applicants WHERE company_id = %s AND status = 'shortlisted'",
            [company_id],
        ),
        "placements_by_status": [
            {"status": row["status"], "n": int(row["n"])}
            for row in db.query_all(
                """
                SELECT p.status, count(*) AS n
                FROM placements p
                JOIN applications a ON a.application_id = p.application_id
                JOIN listings l ON l.listing_id = a.listing_id
                WHERE l.company_id = %s
                GROUP BY p.status
                """,
                [company_id],
            )
        ],
        "unread_messages": _count(
            db,
            "SELECT count(*) AS n FROM messages WHERE recipient_id = %s AND NOT is_read",
            [session.user_id],
        ),
        "unread_notifications": _count(
            db,
            """
            SELECT count(*) AS n FROM notifications
            WHERE user_id = %s AND channel = 'in_app' AND NOT is_read
            """,
            [session.user_id],
        ),
    }


def list_notifications(db, session: Session) -> list[dict]:
    rows = db.query_all(
        """
        SELECT notification_id, title, message, is_read, created_at
        FROM notifications
        WHERE user_id = %s AND channel = 'in_app'
        ORDER BY created_at DESC, notification_id DESC LIMIT 50
        """,
        [session.user_id],
    )
    for row in rows:
        row["is_read"] = bool(row["is_read"])
    return rows


def mark_notification_read(db, session: Session, notification_id: int) -> dict:
    notification_id = as_id(notification_id, "notification_id")

    def action():
        changed = db.execute(
            """
            UPDATE notifications SET is_read = true
            WHERE notification_id = %s AND user_id = %s AND NOT is_read
            """,
            [notification_id, session.user_id],
        )
        if changed == 0:
            # MySQL reports changed rows, not matched rows; a second read is a no-op.
            existing = db.query_one(
                "SELECT notification_id FROM notifications "
                "WHERE notification_id = %s AND user_id = %s",
                [notification_id, session.user_id],
            )
            if existing is None:
                raise ModuleError("not_found", "Notification not found.")
        return {"notification_id": notification_id, "is_read": True}

    return run_write(db, session, action)
