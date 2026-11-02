"""Listing creation, editing, publishing and applicant-facing discovery."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta

from ..constants import LISTING_STATUSES, LISTING_TRANSITIONS, PAGE_SIZE
from ..errors import ModuleError, RULE_MAP
from ..session import Session
from ..validation import prepare_listing
from .common import as_date, as_page, own_listing, run_write, today, utcnow


def _clean_search(value) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ModuleError("invalid", "Search text must be a string.", {"search": "Invalid"})
    value = value.strip()
    return value or None


def _like_pattern(term: str) -> str:
    escaped = (
        term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    return f"%{escaped.lower()}%"


def replace_listing_tags(db, listing_id: int, form: Mapping) -> None:
    """Replace the controlled-vocabulary tags that feed the matching engine (4.6)."""

    for table in ("listing_programmes", "listing_skills", "listing_interests"):
        # Table names are fixed constants, never caller input.
        db.execute(f"DELETE FROM {table} WHERE listing_id = %s", [listing_id])
    for programme_id in form.get("programme_ids", []):
        db.insert(
            "listing_programmes",
            {"listing_id": listing_id, "programme_id": programme_id},
        )
    for skill_id in form.get("required_skill_ids", []):
        db.insert(
            "listing_skills",
            {"listing_id": listing_id, "skill_id": skill_id, "is_required": True},
        )
    for skill_id in form.get("optional_skill_ids", []):
        db.insert(
            "listing_skills",
            {"listing_id": listing_id, "skill_id": skill_id, "is_required": False},
        )
    for interest_id in form.get("interest_ids", []):
        db.insert(
            "listing_interests",
            {"listing_id": listing_id, "interest_id": interest_id},
        )


def create_listing(db, session: Session, form: Mapping) -> dict:
    """Create a listing; it is always saved as a draft first."""

    if not isinstance(form, Mapping):
        raise ModuleError("invalid", "Please correct the form.", {"form": "Invalid"})
    clean, errors = prepare_listing(db, form)
    if errors:
        raise ModuleError("invalid", "Please correct the form.", errors)

    def action():
        listing_id = db.insert_returning_id(
            "listings",
            {
                "company_id": session.company_id,
                "posted_by": session.user_id,
                "title": clean["title"],
                "description": clean["description"],
                "sector": clean["sector"],
                "location": clean["location"],
                "is_remote": clean["is_remote"],
                "duration_weeks": clean["duration_weeks"],
                "slots": clean["slots"],
                "application_deadline": clean["application_deadline"],
                "status": "draft",
            },
        )
        replace_listing_tags(db, listing_id, clean)
        db.log_event("listing_created", "listings", listing_id, result="success")
        return listing_id

    return {"listing_id": run_write(db, session, action)}


def update_listing(
    db, session: Session, listing_id: int, form: Mapping, matching_cache
) -> dict:
    listing = own_listing(db, session, listing_id)
    if not isinstance(form, Mapping):
        raise ModuleError("invalid", "Please correct the form.", {"form": "Invalid"})
    clean, errors = prepare_listing(db, form)
    if errors:
        raise ModuleError("invalid", "Please correct the form.", errors)

    if clean["slots"] is not None and clean["slots"] < int(listing["slots_filled"]):
        raise ModuleError(
            "invalid",
            "Slots cannot be fewer than confirmed placements.",
            {"slots": "Too low"},
        )

    def action():
        db.execute(
            """
            UPDATE listings
            SET title = %s, description = %s, sector = %s, location = %s,
                is_remote = %s, duration_weeks = %s, slots = %s, application_deadline = %s
            WHERE listing_id = %s AND company_id = %s
            """,
            [
                clean["title"],
                clean["description"],
                clean["sector"],
                clean["location"],
                clean["is_remote"],
                clean["duration_weeks"],
                clean["slots"],
                clean["application_deadline"],
                listing_id,
                session.company_id,
            ],
        )
        replace_listing_tags(db, listing_id, clean)
        db.log_event("listing_updated", "listings", listing_id, result="success")

    run_write(db, session, action)
    matching_cache.invalidate_all()
    return get_listing_detail(db, session, listing_id)


def change_listing_status(
    db, session: Session, listing_id: int, new_status: str, matching_cache
) -> dict:
    listing = own_listing(db, session, listing_id)
    if not isinstance(new_status, str) or new_status not in LISTING_STATUSES:
        raise ModuleError("invalid", "Unknown listing status.", {"status": "Invalid"})
    if new_status not in LISTING_TRANSITIONS.get(listing["status"], set()):
        raise ModuleError("conflict", RULE_MAP["RULE_LISTING_TRANSITION"][1])

    if new_status == "open":
        # Friendly early checks; the database remains the final authority.
        company = db.query_one(
            "SELECT verification_status FROM companies WHERE company_id = %s",
            [session.company_id],
        )
        if company is None or company["verification_status"] != "verified":
            raise ModuleError(*RULE_MAP["RULE_SR07_COMPANY_NOT_VERIFIED"])
        deadline = as_date(listing["application_deadline"])
        if deadline is None or deadline < today():
            raise ModuleError(*RULE_MAP["RULE_SR08_DEADLINE_PAST"])

    def action():
        now = utcnow()
        if new_status == "open":
            changed = db.execute(
                """
                UPDATE listings
                SET status = %s, posted_at = COALESCE(posted_at, %s), closed_at = NULL
                WHERE listing_id = %s AND company_id = %s AND status = %s
                """,
                [new_status, now, listing_id, session.company_id, listing["status"]],
            )
        elif new_status == "closed":
            changed = db.execute(
                """
                UPDATE listings SET status = %s, closed_at = %s
                WHERE listing_id = %s AND company_id = %s AND status = %s
                """,
                [new_status, now, listing_id, session.company_id, listing["status"]],
            )
        else:
            changed = db.execute(
                """
                UPDATE listings SET status = %s
                WHERE listing_id = %s AND company_id = %s AND status = %s
                """,
                [new_status, listing_id, session.company_id, listing["status"]],
            )
        if changed != 1:
            raise ModuleError(
                "conflict", "This listing was already updated. Refresh and try again."
            )
        db.log_event(
            "listing_status_changed",
            "listings",
            listing_id,
            result="success",
            details={"from": listing["status"], "to": new_status},
        )

    run_write(db, session, action)
    matching_cache.invalidate_all()
    return get_listing_detail(db, session, listing_id)


def list_my_listings(
    db, session: Session, status=None, search=None, page=1
) -> list[dict]:
    page = as_page(page)
    if status in ("", None):
        status = None
    elif not isinstance(status, str) or status not in LISTING_STATUSES:
        raise ModuleError("invalid", "Unknown listing status.", {"status": "Invalid"})

    term = _clean_search(search)
    pattern = _like_pattern(term) if term else None
    rows = db.query_all(
        """
        SELECT l.listing_id, l.title, l.status, l.slots, l.slots_filled,
               l.application_deadline, l.posted_at,
               (SELECT count(*) FROM applications a
                WHERE a.listing_id = l.listing_id) AS applicants,
               (SELECT count(*) FROM applications a
                WHERE a.listing_id = l.listing_id AND a.status = 'submitted') AS new_applicants
        FROM listings l
        WHERE l.company_id = %s
          AND (%s IS NULL OR l.status = %s)
          AND (%s IS NULL
               OR LOWER(l.title) LIKE %s ESCAPE '\\'
               OR LOWER(l.description) LIKE %s ESCAPE '\\')
        ORDER BY l.created_at DESC, l.listing_id DESC
        LIMIT %s OFFSET %s
        """,
        [
            session.company_id,
            status,
            status,
            term,
            pattern,
            pattern,
            PAGE_SIZE,
            (page - 1) * PAGE_SIZE,
        ],
    )
    for row in rows:
        row["applicants"] = int(row["applicants"])
        row["new_applicants"] = int(row["new_applicants"])
    return rows


def get_listing_detail(db, session: Session, listing_id: int) -> dict:
    listing = own_listing(db, session, listing_id)
    listing["skills"] = db.query_all(
        """
        SELECT s.name, ls.is_required
        FROM listing_skills ls JOIN skills s ON s.skill_id = ls.skill_id
        WHERE ls.listing_id = %s ORDER BY s.name
        """,
        [listing_id],
    )
    listing["programmes"] = db.query_all(
        """
        SELECT p.name
        FROM listing_programmes lp JOIN programmes p ON p.programme_id = lp.programme_id
        WHERE lp.listing_id = %s ORDER BY p.name
        """,
        [listing_id],
    )
    listing["interests"] = db.query_all(
        """
        SELECT i.name
        FROM listing_interests li JOIN interests i ON i.interest_id = li.interest_id
        WHERE li.listing_id = %s ORDER BY i.name
        """,
        [listing_id],
    )
    for skill in listing["skills"]:
        skill["is_required"] = bool(skill["is_required"])
    return listing


def daily_listing_job(db, notifier, matching_cache=None) -> dict:
    """Close expired listings and remind employers two days before deadline."""

    current_day = date.today()
    reminder_day = current_day + timedelta(days=2)
    with db.transaction():
        db.set_actor(None)  # scheduled system action, never a stale request actor
        closed = db.execute(
            """
            UPDATE listings SET status = 'closed', closed_at = %s
            WHERE status = 'open' AND application_deadline < %s
            """,
            [utcnow(), current_day],
        )
        soon = db.query_all(
            """
            SELECT listing_id, company_id, title FROM listings
            WHERE status = 'open' AND application_deadline = %s
            """,
            [reminder_day],
        )
        if closed:
            db.log_event(
                "listings_auto_closed", result="success", details={"count": closed}
            )

    if closed and matching_cache is not None:
        matching_cache.invalidate_all()

    reminders = 0
    for listing in soon:
        users = db.query_all(
            "SELECT user_id FROM users WHERE company_id = %s AND status = 'active'",
            [listing["company_id"]],
        )
        for user in users:
            notifier.notify(
                int(user["user_id"]),
                "deadline_reminder",
                "Listing closes soon",
                f'"{listing["title"]}" closes in 2 days.',
                "listings",
                int(listing["listing_id"]),
            )
            reminders += 1
    return {"closed": int(closed), "reminders_sent": reminders}
