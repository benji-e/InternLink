"""Shortlist-only messaging between an employer and a candidate (SR10)."""

from __future__ import annotations

from ..constants import MAX_MESSAGE_LEN
from ..errors import ModuleError, RULE_MAP
from ..session import Session
from .common import (
    lock_application_for_update,
    notify_user,
    own_application,
    run_write,
    student_user_id,
)


def send_message(db, session: Session, application_id: int, body) -> dict:
    application = own_application(db, session, application_id)
    if not isinstance(body, str):
        raise ModuleError(
            "invalid", f"Message must be 1 to {MAX_MESSAGE_LEN} characters.", {"body": "Required"}
        )
    body = body.strip()
    if not body or len(body) > MAX_MESSAGE_LEN:
        raise ModuleError(
            "invalid",
            f"Message must be 1 to {MAX_MESSAGE_LEN} characters.",
            {"body": "Required" if not body else "Too long"},
        )
    if application["status"] not in ("shortlisted", "accepted"):
        raise ModuleError(*RULE_MAP["RULE_SR10_NOT_SHORTLISTED"])

    recipient = student_user_id(db, application["student_id"])
    if recipient is None:
        raise ModuleError("not_found", "Applicant not found.")

    def action():
        # Re-check under the transaction: a decision may have landed since the
        # friendly check above (for example a teammate rejecting the candidate).
        lock_application_for_update(db, application_id)
        current = db.query_one(
            "SELECT status FROM applications WHERE application_id = %s",
            [application_id],
        )
        if current is None or current["status"] not in ("shortlisted", "accepted"):
            raise ModuleError(*RULE_MAP["RULE_SR10_NOT_SHORTLISTED"])
        message_id = db.insert_returning_id(
            "messages",
            {
                "application_id": application_id,
                "sender_id": session.user_id,
                "recipient_id": recipient,
                "body": body,
            },
        )
        notify_user(
            db,
            recipient,
            "message",
            "New message from an employer",
            f'You have a new message about "{application["title"]}".',
            "applications",
            application_id,
        )
        db.log_event("message_sent", "applications", application_id, result="success")
        return message_id

    run_write(db, session, action)
    return {"sent": True}


def get_thread(db, session: Session, application_id: int) -> list[dict]:
    own_application(db, session, application_id)
    run_write(
        db,
        session,
        lambda: db.execute(
            """
            UPDATE messages SET is_read = true
            WHERE application_id = %s AND recipient_id = %s AND NOT is_read
            """,
            [application_id, session.user_id],
        ),
    )
    messages = db.query_all(
        """
        SELECT message_id, sender_id, body, sent_at, is_read
        FROM messages WHERE application_id = %s ORDER BY sent_at ASC, message_id ASC
        """,
        [application_id],
    )
    for message in messages:
        message["mine"] = int(message["sender_id"]) == session.user_id
        message["is_read"] = bool(message["is_read"])
        message.pop("sender_id", None)
    return messages


def list_conversations(db, session: Session) -> list[dict]:
    rows = db.query_all(
        """
        SELECT m.application_id, u.full_name AS applicant_name,
               l.title AS listing_title, a.status AS application_status,
               max(m.sent_at) AS last_message_at,
               sum(CASE WHEN m.recipient_id = %s AND NOT m.is_read THEN 1 ELSE 0 END) AS unread
        FROM messages m
        JOIN applications a ON a.application_id = m.application_id
        JOIN listings l ON l.listing_id = a.listing_id
        JOIN student_profiles sp ON sp.student_id = a.student_id
        JOIN users u ON u.user_id = sp.user_id
        WHERE l.company_id = %s
        GROUP BY m.application_id, u.full_name, l.title, a.status
        ORDER BY last_message_at DESC
        """,
        [session.user_id, session.company_id],
    )
    for row in rows:
        row["unread"] = int(row["unread"] or 0)
    return rows
