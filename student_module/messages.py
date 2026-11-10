"""The student side of employer conversations.

Employers start a conversation once they shortlist a student (SR10). The
student can then read it and reply while the application is shortlisted or
accepted. Database triggers create the notification for the other side.
"""

from __future__ import annotations

from psycopg.rows import dict_row

from .service import StudentError

MAX_MESSAGE_LENGTH = 5000
OPEN_STATUSES = ("shortlisted", "interview", "accepted")


def _application(cur, student_id: int, application_id: int) -> dict:
    row = cur.execute(
        """
        SELECT a.application_id, a.status, l.title, c.name AS company_name
        FROM applications a
        JOIN listings l ON l.listing_id = a.listing_id
        JOIN companies c ON c.company_id = l.company_id
        WHERE a.application_id = %s AND a.student_id = %s
        """,
        (application_id, student_id),
    ).fetchone()
    if row is None:
        raise StudentError(404, "APPLICATION_NOT_FOUND", "Application not found.")
    return row


def thread(conn, user_id: int, student_id: int, application_id: int) -> dict:
    """Messages for one application, oldest first. Marks incoming ones as read."""
    with conn.cursor(row_factory=dict_row) as cur:
        application = _application(cur, student_id, application_id)
        cur.execute(
            "UPDATE messages SET is_read = true, read_at = now() "
            "WHERE application_id = %s AND recipient_id = %s AND NOT is_read",
            (application_id, user_id),
        )
        messages = cur.execute(
            """
            SELECT m.message_id, m.body, m.sent_at, m.is_read, (m.sender_id = %s) AS mine,
                   u.full_name AS sender_name
            FROM messages m JOIN users u ON u.user_id = m.sender_id
            WHERE m.application_id = %s
            ORDER BY m.sent_at, m.message_id
            """,
            (user_id, application_id),
        ).fetchall()
    employer = next((item["sender_name"] for item in messages if not item["mine"]), None)
    return {
        "application": application,
        "employer_name": employer,
        "messages": messages,
        # Students reply to an employer's conversation; they don't start one.
        "can_reply": application["status"] in OPEN_STATUSES and employer is not None,
    }


def reply(conn, user_id: int, student_id: int, application_id: int, payload: dict) -> dict:
    body = payload.get("body")
    body = body.strip() if isinstance(body, str) else ""
    if not body or len(body) > MAX_MESSAGE_LENGTH:
        raise StudentError(422, "INVALID_MESSAGE", f"Write a message of 1 to {MAX_MESSAGE_LENGTH} characters.")
    with conn.cursor(row_factory=dict_row) as cur:
        application = _application(cur, student_id, application_id)
        cur.execute("SELECT 1 FROM applications WHERE application_id = %s FOR UPDATE", (application_id,))
        if application["status"] not in OPEN_STATUSES:
            raise StudentError(409, "CONVERSATION_CLOSED", "You can only message employers who shortlisted you.")
        last = cur.execute(
            "SELECT sender_id FROM messages WHERE application_id = %s AND sender_id <> %s "
            "ORDER BY sent_at DESC, message_id DESC LIMIT 1",
            (application_id, user_id),
        ).fetchone()
        if last is None:
            raise StudentError(409, "CONVERSATION_NOT_STARTED", "The employer hasn't messaged you about this application yet.")
        message = cur.execute(
            """
            INSERT INTO messages (application_id, sender_id, recipient_id, body)
            VALUES (%s, %s, %s, %s)
            RETURNING message_id, body, sent_at, is_read, true AS mine
            """,
            (application_id, user_id, last["sender_id"], body),
        ).fetchone()
    return {"message": message}


def unread_by_application(conn, user_id: int) -> dict[int, int]:
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT application_id, count(*) AS n FROM messages WHERE recipient_id = %s AND NOT is_read GROUP BY application_id",
            (user_id,),
        ).fetchall()
    return {int(row["application_id"]): int(row["n"]) for row in rows}
