"""Placement listing and completion (SR11)."""

from __future__ import annotations

from datetime import date

from ..constants import MAX_COMPLETION_NOTE_LEN, PLACEMENT_STATUSES
from ..errors import ModuleError, RULE_MAP
from ..session import Session
from .common import (
    as_date,
    as_id,
    lock_listing_for_update,
    notify_user,
    recount_slots,
    run_write,
    student_user_id,
    today,
    utcnow,
)


def list_my_placements(db, session: Session, status=None) -> list[dict]:
    """List placements for the company, including those awaiting approval.

    Pending placements are read-only in the UI; ``can_complete`` is only true
    for confirmed placements whose end date has passed.
    """

    if status in ("", None):
        status = None
    elif not isinstance(status, str) or status not in PLACEMENT_STATUSES:
        raise ModuleError("invalid", "Unknown placement status.", {"status": "Invalid"})

    rows = db.query_all(
        """
        SELECT p.placement_id, u.full_name AS student_name, pr.name AS programme,
               l.title AS listing_title, p.status, p.start_date, p.end_date,
               p.completion_note,
               (p.status = 'confirmed' AND p.end_date IS NOT NULL AND p.end_date <= %s) AS can_complete
        FROM placements p
        JOIN applications a ON a.application_id = p.application_id
        JOIN listings l ON l.listing_id = a.listing_id
        JOIN student_profiles sp ON sp.student_id = a.student_id
        JOIN users u ON u.user_id = sp.user_id
        JOIN programmes pr ON pr.programme_id = sp.programme_id
        WHERE l.company_id = %s
          AND p.status IN ('pending', 'confirmed', 'completed')
          AND (CAST(%s AS TEXT) IS NULL OR p.status = %s)
        ORDER BY COALESCE(p.end_date, %s), p.placement_id
        """,
        [
            today(),
            session.company_id,
            status,
            status,
            date(9999, 12, 31),
        ],
    )
    for row in rows:
        end_date = as_date(row["end_date"])
        row["can_complete"] = bool(
            row["status"] == "confirmed" and end_date is not None and end_date <= today()
        )
        row["awaiting_approval"] = row["status"] == "pending"
    return rows


def complete_placement(db, session: Session, placement_id: int, note) -> dict:
    placement_id = as_id(placement_id, "placement_id")
    placement = db.query_one(
        """
        SELECT p.placement_id, p.status, p.end_date, p.application_id,
               a.listing_id, l.company_id, l.title, a.student_id
        FROM placements p
        JOIN applications a ON a.application_id = p.application_id
        JOIN listings l ON l.listing_id = a.listing_id
        WHERE p.placement_id = %s
        """,
        [placement_id],
    )
    if placement is None or placement["company_id"] != session.company_id:
        raise ModuleError("not_found", "Placement not found.")
    if placement["status"] != "confirmed":
        raise ModuleError("conflict", "Only confirmed placements can be completed.")

    end_date = as_date(placement["end_date"])
    if end_date is None:
        raise ModuleError("conflict", "This placement has no end date yet.")
    if end_date > today():
        raise ModuleError(*RULE_MAP["RULE_SR11_NOT_ENDED"])

    if not isinstance(note, str) or not note.strip():
        raise ModuleError(
            "invalid", "A short performance note is required.", {"completion_note": "Required"}
        )
    note = note.strip()
    if len(note) > MAX_COMPLETION_NOTE_LEN:
        raise ModuleError(
            "invalid",
            f"The performance note must be at most {MAX_COMPLETION_NOTE_LEN} characters.",
            {"completion_note": "Too long"},
        )

    def action():
        lock_listing_for_update(db, placement["listing_id"])
        changed = db.execute(
            """
            UPDATE placements
            SET status = 'completed', completion_note = %s,
                completed_by = %s, completed_at = %s
            WHERE placement_id = %s AND status = 'confirmed'
            """,
            [note, session.user_id, utcnow(), placement_id],
        )
        if changed != 1:
            raise ModuleError("conflict", "Only confirmed placements can be completed.")
        recount_slots(db, placement["listing_id"])
        db.log_event(
            "placement_completed", "placements", placement_id, result="success"
        )
        recipient = student_user_id(db, placement["student_id"])
        if recipient is not None:
            notify_user(
                db,
                recipient,
                "placement_completed",
                "Placement completed",
                f'Your placement for "{placement["title"]}" has been marked complete.',
                "placements",
                placement_id,
            )

    run_write(db, session, action)
    return {"placement_id": placement_id, "status": "completed"}
