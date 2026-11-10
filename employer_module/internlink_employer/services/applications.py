"""Applicant listing, review, CV download and decision services (SR04/SR09)."""

from __future__ import annotations

from datetime import datetime, timezone

from ..constants import (
    ACTION_TO_STATUS,
    APPLICATION_STATUSES,
    EMPLOYER_APP_TRANSITIONS,
    PAGE_SIZE,
    SORT_WHITELIST,
    MAX_DECISION_NOTE_LEN,
    MESSAGING_STATUSES,
)
from ..errors import ModuleError, RULE_MAP
from ..session import Session
from .common import (
    active_placement_count,
    as_bool,
    as_id,
    as_page,
    lock_listing_for_update,
    notify_user,
    own_application,
    own_listing,
    recount_slots,
    run_write,
    student_user_id,
    utcnow,
)

DECISION_MESSAGES = {
    "under_review": ("Application under review", "Your application is now under review."),
    "shortlisted": ("Application shortlisted", "You have been shortlisted for an internship."),
    "interview": ("Interview invitation", "You have been invited to an interview."),
    "accepted": ("Application accepted", "You have been accepted for an internship placement."),
    "rejected": ("Application update", "Your application was not successful this time."),
}


def list_applicants(
    db,
    session: Session,
    listing_id: int,
    status=None,
    sort: str = "match_score",
    desc: bool = True,
    page: int = 1,
) -> dict:
    """Applicant list for one owned listing (SR09)."""

    own_listing(db, session, listing_id)
    page = as_page(page)
    if status in ("", None):
        status = None
    elif not isinstance(status, str) or status not in APPLICATION_STATUSES:
        raise ModuleError("invalid", "Unknown application status.", {"status": "Invalid"})

    if not isinstance(sort, str):
        sort = "match_score"
    column = SORT_WHITELIST.get(sort, "match_score")  # raw input never enters SQL
    direction = "DESC" if as_bool(desc, default=True) else "ASC"
    rows = db.query_all(
        f"""
        SELECT application_id, student_id, applicant_name, programme, year_of_study,
               university, match_score, status, submitted_at,
               (cv_path IS NOT NULL) AS has_cv, student_verified, interview_at
        FROM v_employer_applicants
        WHERE company_id = %s AND listing_id = %s AND (CAST(%s AS TEXT) IS NULL OR status = %s)
        ORDER BY CASE WHEN {column} IS NULL THEN 1 ELSE 0 END,
                 {column} {direction}, submitted_at ASC
        LIMIT %s OFFSET %s
        """,
        [
            session.company_id,
            listing_id,
            status,
            status,
            PAGE_SIZE,
            (page - 1) * PAGE_SIZE,
        ],
    )
    for row in rows:
        row["has_cv"] = bool(row["has_cv"])
        row["student_verified"] = bool(row["student_verified"])

    counts = db.query_all(
        """
        SELECT status, count(*) AS n
        FROM v_employer_applicants
        WHERE company_id = %s AND listing_id = %s
        GROUP BY status
        """,
        [session.company_id, listing_id],
    )
    for row in counts:
        row["n"] = int(row["n"])
    return {"applicants": rows, "counts_by_status": counts}


def view_applicant(db, session: Session, application_id: int) -> dict:
    """Show a candidate profile, moving a fresh application into review."""

    application = own_application(db, session, application_id)
    profile = db.query_one(
        """
        SELECT u.full_name, pr.name AS programme, sp.year_of_study,
               un.name AS university, sp.preferred_location, sp.willing_to_relocate,
               (sp.cv_path IS NOT NULL) AS has_cv
        FROM student_profiles sp
        JOIN users u ON u.user_id = sp.user_id
        JOIN programmes pr ON pr.programme_id = sp.programme_id
        JOIN universities un ON un.university_id = sp.university_id
        WHERE sp.student_id = %s
        """,
        [application["student_id"]],
    )
    if profile is None:
        raise ModuleError("not_found", "Applicant profile not found.")
    # Contact details and student number are deliberately not exposed.
    profile["skills"] = db.query_all(
        """
        SELECT s.name FROM student_skills ss JOIN skills s ON s.skill_id = ss.skill_id
        WHERE ss.student_id = %s ORDER BY s.name
        """,
        [application["student_id"]],
    )
    profile["interests"] = db.query_all(
        """
        SELECT i.name FROM student_interests si JOIN interests i ON i.interest_id = si.interest_id
        WHERE si.student_id = %s ORDER BY i.name
        """,
        [application["student_id"]],
    )
    profile["willing_to_relocate"] = bool(profile["willing_to_relocate"])
    has_cv = bool(profile.pop("has_cv"))

    status = application["status"]
    if status == "submitted":

        def mark_reviewed() -> bool:
            changed = db.execute(
                """
                UPDATE applications SET status = 'under_review'
                WHERE application_id = %s AND status = 'submitted'
                """,
                [application_id],
            )
            if changed:
                db.log_event(
                    "application_under_review",
                    "applications",
                    application_id,
                    result="success",
                )
            return changed == 1

        if run_write(db, session, mark_reviewed):
            status = "under_review"
        else:
            current = db.query_one(
                "SELECT status FROM applications WHERE application_id = %s",
                [application_id],
            )
            status = current["status"] if current else status

    # The listing's skills, marked with whether this candidate has each one.
    student_skills = {row["name"] for row in profile["skills"]}
    listing_skills = db.query_all(
        """
        SELECT s.name, ls.is_required FROM listing_skills ls JOIN skills s ON s.skill_id = ls.skill_id
        WHERE ls.listing_id = %s ORDER BY ls.is_required DESC, s.name
        """,
        [application["listing_id"]],
    )
    return {
        "profile": profile,
        "application_id": int(application["application_id"]),
        "listing_id": int(application["listing_id"]),
        "listing_title": application["title"],
        "submitted_at": application["submitted_at"],
        "cover_note": application["cover_note"],
        "match_score": application["match_score"],
        "status": status,
        "has_cv": has_cv,
        "interview_at": application.get("interview_at"),
        "interview_note": application.get("interview_note"),
        "listing_skills": [
            {"name": row["name"], "required": bool(row["is_required"]), "has": row["name"] in student_skills}
            for row in listing_skills
        ],
        "can_message": status in MESSAGING_STATUSES,
    }


def download_applicant_cv(db, session: Session, storage, application_id: int) -> bytes:
    """Return CV bytes after verifying the application belongs to the company."""

    application = own_application(db, session, application_id)  # ownership first
    cv = db.query_one(
        "SELECT cv_path FROM student_profiles WHERE student_id = %s",
        [application["student_id"]],
    )
    if cv is None or cv["cv_path"] is None:
        raise ModuleError("not_found", "No CV uploaded.")

    try:
        # Private folder outside the web root; adapter enforces path containment.
        content = storage.read_bytes(cv["cv_path"])
    except FileNotFoundError:
        raise ModuleError("not_found", "No CV uploaded.") from None
    except PermissionError:
        raise ModuleError("forbidden", "This CV is not accessible.") from None

    run_write(
        db,
        session,
        lambda: db.log_event(
            "cv_downloaded", "applications", application_id, result="success"
        ),
    )
    return content


def _interview_time(value) -> datetime:
    """An ISO date-time in the future, returned as an aware UTC datetime.

    Unlike decided_at, this is shown to people, so it keeps its time zone:
    a naive value would be read in the database server's own zone.
    """

    if not isinstance(value, str) or not value.strip():
        raise ModuleError("invalid", "Choose the interview date and time.", {"interview_at": "Required"})
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise ModuleError("invalid", "Choose a valid interview date and time.", {"interview_at": "Invalid"}) from None
    # A time without a zone is taken as UTC.
    moment = moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)
    if moment <= datetime.now(timezone.utc):
        raise ModuleError("invalid", "The interview must be in the future.", {"interview_at": "Past"})
    return moment


def _short_note(value, label: str) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or len(value.strip()) > MAX_DECISION_NOTE_LEN:
        raise ModuleError("invalid", f"{label} must be at most {MAX_DECISION_NOTE_LEN} characters.")
    return value.strip() or None


def decide_application(
    db,
    session: Session,
    application_id: int,
    action: str,
    *,
    interview_at=None,
    interview_note=None,
    reason=None,
) -> dict:
    """Move one application through the employer-side state machine (SR04).

    An interview needs a future date and time. A rejection can carry a short
    reason that is shared with the student.
    """

    if not isinstance(action, str):
        raise ModuleError("invalid", "Unknown action.")
    target = ACTION_TO_STATUS.get(action)
    if target is None:
        raise ModuleError("invalid", "Unknown action.")
    extra: dict = {}
    if target == "interview":
        extra["interview_at"] = _interview_time(interview_at)
        extra["interview_note"] = _short_note(interview_note, "Interview details")
    if target == "rejected":
        extra["decision_note"] = _short_note(reason, "The reason")
    application = own_application(db, session, application_id)
    current_status = application["status"]
    if target not in EMPLOYER_APP_TRANSITIONS.get(current_status, set()):
        raise ModuleError(
            "conflict",
            f"Cannot move from {current_status} to {target}.",
        )

    def act():
        lock_listing_for_update(db, application["listing_id"])
        if target == "accepted":
            listing = db.query_one(
                "SELECT slots FROM listings WHERE listing_id = %s",
                [application["listing_id"]],
            )
            used = active_placement_count(db, application["listing_id"])
            if listing is None or used >= int(listing["slots"]):
                raise ModuleError("conflict", "All slots of this listing are filled.")

        # Conditional update protects against a concurrent decision by a teammate.
        # Column names come from the fixed `extra` keys above, never from input.
        assignments = "".join(f", {column} = %s" for column in extra)
        changed = db.execute(
            f"""
            UPDATE applications SET status = %s, decided_at = %s{assignments}
            WHERE application_id = %s AND status = %s
            """,
            [target, utcnow(), *extra.values(), application_id, current_status],
        )
        if changed != 1:
            raise ModuleError(
                "conflict", "This application was already updated. Refresh and try again."
            )

        if target == "accepted":
            db.insert(
                "placements",
                {"application_id": application_id, "status": "pending"},
            )
            recount_slots(db, application["listing_id"])

        db.log_event(
            "application_decided",
            "applications",
            application_id,
            result="success",
            details={"from": current_status, "to": target},
        )

        recipient = student_user_id(db, application["student_id"])
        if recipient is not None:
            title, message = DECISION_MESSAGES[target]
            if target == "interview":
                message = f"{message} When: {extra['interview_at']:%d %b %Y, %H:%M} UTC."
            if extra.get("decision_note"):
                message = f"{message} Reason: {extra['decision_note']}"
            notify_user(
                db,
                recipient,
                "application_status",
                title,
                f'{message} Listing: "{application["title"]}".',
                "applications",
                application_id,
            )

    run_write(db, session, act)
    note = (
        "Sent to the university coordinator for placement approval."
        if target == "accepted"
        else None
    )
    return {"application_id": application_id, "status": target, "info": note}


def bulk_decide(db, session: Session, application_ids, action: str) -> list[dict]:
    """Shortlist/reject up to 100 applications; one failure does not stop the rest."""

    if (
        not isinstance(application_ids, (list, tuple))
        or not (1 <= len(application_ids) <= 100)
        or action not in ("shortlist", "reject")
    ):
        raise ModuleError(
            "invalid", "Choose 1 to 100 applications and shortlist or reject."
        )

    ids = [as_id(value, "application_id") for value in application_ids]
    results = []
    for application_id in ids:
        try:
            decide_application(db, session, application_id, action)
            results.append({"id": application_id, "ok": True})
        except ModuleError as err:
            results.append({"id": application_id, "ok": False, "message": err.message})
    return results
