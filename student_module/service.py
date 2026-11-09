"""PostgreSQL-backed student services used by the Vercel API."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

import bcrypt
from psycopg.rows import dict_row
from employer_module.internlink_employer.security import verify_password as verify_employer_password


class StudentError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _clean_text(value: Any, label: str, *, max_length: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise StudentError(422, "INVALID_INPUT", f"{label} is required.")
    text = value.strip()
    if (required and not text) or len(text) > max_length:
        raise StudentError(422, "INVALID_INPUT", f"Check the {label.lower()} field.")
    return text


def list_universities(conn) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            "SELECT university_id AS id, name, location FROM universities "
            "WHERE status = 'verified' ORDER BY name"
        ).fetchall()


def list_departments(conn, university_id: int) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            "SELECT department_id AS id, name FROM departments "
            "WHERE university_id = %s ORDER BY name",
            (university_id,),
        ).fetchall()


def list_programmes(conn, department_id: int) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            "SELECT programme_id AS id, name FROM programmes "
            "WHERE department_id = %s ORDER BY name",
            (department_id,),
        ).fetchall()


def get_catalogs(conn) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        skills = cur.execute("SELECT skill_id AS id, name FROM skills ORDER BY name").fetchall()
        interests = cur.execute(
            "SELECT interest_id AS id, name FROM interests ORDER BY name"
        ).fetchall()
    return {"skills": skills, "interests": interests}


def register_student(conn, payload: dict, verification_token: str) -> dict:
    full_name = _clean_text(payload.get("full_name"), "Full name", max_length=160)
    email = _clean_text(payload.get("email"), "Email", max_length=254).lower()
    password = _clean_text(payload.get("password"), "Password", max_length=128)
    if not EMAIL_RE.fullmatch(email):
        raise StudentError(422, "INVALID_EMAIL", "Enter a valid university email address.")
    if len(password) < 10:
        raise StudentError(422, "WEAK_PASSWORD", "Use a password with at least 10 characters.")

    try:
        university_id = int(payload.get("university_id"))
        department_id = int(payload.get("department_id"))
        programme_id = int(payload.get("programme_id"))
        year_of_study = int(payload.get("year_of_study"))
    except (TypeError, ValueError):
        raise StudentError(422, "INVALID_INPUT", "Choose your university, department, programme and year.") from None
    if min(university_id, department_id, programme_id) <= 0 or not 1 <= year_of_study <= 6:
        raise StudentError(422, "INVALID_INPUT", "Check your university and study details.")

    student_number = _clean_text(
        payload.get("student_number"), "Student number", max_length=80
    )
    phone = payload.get("phone")
    if phone is not None:
        phone = _clean_text(phone, "Phone", max_length=32, required=False) or None
    try:
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")
    except ValueError:
        raise StudentError(422, "WEAK_PASSWORD", "Use a password of at most 72 UTF-8 bytes.") from None
    token_hash = hashlib.sha256(verification_token.encode("utf-8")).hexdigest()

    with conn.cursor(row_factory=dict_row) as cur:
        university = cur.execute(
            """
            SELECT university_id, email_domain
            FROM universities
            WHERE university_id = %s AND status = 'verified'
            """,
            (university_id,),
        ).fetchone()
        if university is None:
            raise StudentError(422, "UNIVERSITY_UNAVAILABLE", "Choose a verified university.")
        email_domain = email.rsplit("@", 1)[1]
        domain = university["email_domain"]
        if email_domain != domain and not email_domain.endswith(f".{domain}"):
            raise StudentError(
                422, "UNIVERSITY_EMAIL_REQUIRED",
                f"Use an email address belonging to {university['email_domain']}.",
            )
        programme = cur.execute(
            """
            SELECT p.programme_id
            FROM programmes p
            JOIN departments d ON d.department_id = p.department_id
            WHERE p.programme_id = %s AND d.department_id = %s
              AND d.university_id = %s
            """,
            (programme_id, department_id, university_id),
        ).fetchone()
        if programme is None:
            raise StudentError(422, "INVALID_PROGRAMME", "Choose a programme from your department.")

        user = cur.execute(
            """
            INSERT INTO users (email, password_hash, full_name, phone, role, status)
            VALUES (%s, %s, %s, %s, 'student', 'pending')
            RETURNING user_id
            """,
            (email, password_hash, full_name, phone),
        ).fetchone()
        student = cur.execute(
            """
            INSERT INTO student_profiles
                (user_id, university_id, department_id, programme_id,
                 student_number, year_of_study)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING student_id
            """,
            (
                user["user_id"], university_id, department_id, programme_id,
                student_number, year_of_study,
            ),
        ).fetchone()
        cur.execute(
            """
            INSERT INTO auth_tokens (user_id, purpose, token_hash, expires_at)
            VALUES (%s, 'email_verify', %s, now() + interval '24 hours')
            """,
            (user["user_id"], token_hash),
        )
    return {"user_id": int(user["user_id"]), "student_id": int(student["student_id"])}


def verify_student_email(conn, verification_token: str) -> dict:
    """Compatibility name; verification now lives in accounts.verify_account_email."""
    from .accounts import verify_account_email

    return verify_account_email(conn, verification_token)


def authenticate_user(conn, email: str, password: str, expected_role: str | None = None) -> dict:
    email = email.strip().lower() if isinstance(email, str) else ""
    if not EMAIL_RE.fullmatch(email) or not isinstance(password, str) or not password:
        raise StudentError(401, "INVALID_CREDENTIALS", "Email or password is incorrect.")

    failure: StudentError | None = None
    account: dict | None = None
    with conn.transaction():
        with conn.cursor(row_factory=dict_row) as cur:
            user = cur.execute(
                """
                SELECT user_id, email, full_name, password_hash, role, status,
                       failed_login_count, locked_until
                FROM users WHERE lower(email) = %s FOR UPDATE
                """,
                (email,),
            ).fetchone()
            if user is None or (expected_role and user["role"] != expected_role):
                failure = StudentError(401, "INVALID_CREDENTIALS", "Email or password is incorrect.")
            elif user["locked_until"] is not None and user["locked_until"] > datetime.now(timezone.utc):
                failure = StudentError(423, "ACCOUNT_LOCKED", "Too many attempts. Try again after the lock expires.")
            else:
                stored_hash = user["password_hash"]
                if isinstance(stored_hash, str) and stored_hash.startswith("$2"):
                    try:
                        valid_password = bcrypt.checkpw(
                            password.encode("utf-8"), stored_hash.encode("ascii")
                        )
                    except (ValueError, TypeError):
                        valid_password = False
                else:
                    valid_password = verify_employer_password(password, stored_hash)
                if not valid_password:
                    cur.execute(
                        """
                        UPDATE users
                        SET failed_login_count = failed_login_count + 1,
                            locked_until = CASE WHEN failed_login_count + 1 >= 5
                                THEN now() + interval '15 minutes' ELSE NULL END
                        WHERE user_id = %s
                        """,
                        (user["user_id"],),
                    )
                    failure = StudentError(401, "INVALID_CREDENTIALS", "Email or password is incorrect.")
                elif user["status"] != "active":
                    failure = StudentError(
                        403, "ACCOUNT_PENDING",
                        "Verify your email and wait for any required account review.",
                    )
                else:
                    cur.execute(
                        "UPDATE users SET failed_login_count = 0, locked_until = NULL, last_login_at = now() WHERE user_id = %s",
                        (user["user_id"],),
                    )
                    account = {
                        "user_id": int(user["user_id"]),
                        "email": user["email"],
                        "full_name": user["full_name"],
                        "role": user["role"],
                    }
    if failure:
        raise failure
    if account is None:
        raise RuntimeError("Student authentication completed without an account or error.")
    return account


def authenticate_student(conn, email: str, password: str) -> dict:
    """Compatibility wrapper retaining the student-only login contract."""
    account = authenticate_user(conn, email, password, expected_role="student")
    account.pop("role", None)
    return account


def student_id_for_user(conn, user_id: int) -> int:
    row = conn.execute(
        """
        SELECT sp.student_id
        FROM student_profiles sp
        JOIN users u ON u.user_id = sp.user_id
        WHERE sp.user_id = %s AND u.role = 'student' AND u.status = 'active'
        """,
        (user_id,),
    ).fetchone()
    if row is None:
        raise StudentError(403, "STUDENT_ACCOUNT_REQUIRED", "An active student account is required.")
    return int(row[0])


def get_profile(conn, student_id: int) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        profile = cur.execute(
            """
            SELECT sp.student_id, sp.student_number, sp.year_of_study,
                   sp.preferred_location, sp.willing_to_relocate, sp.verified,
                   u.full_name, u.email, u.phone,
                   un.university_id, un.name AS university,
                   d.department_id, d.name AS department,
                   p.programme_id, p.name AS programme,
                   s.completeness_pct, s.is_complete
            FROM student_profiles sp
            JOIN users u ON u.user_id = sp.user_id
            JOIN universities un ON un.university_id = sp.university_id
            JOIN departments d ON d.department_id = sp.department_id
            JOIN programmes p ON p.programme_id = sp.programme_id
            JOIN v_student_profile_status s ON s.student_id = sp.student_id
            WHERE sp.student_id = %s
            """,
            (student_id,),
        ).fetchone()
        if profile is None:
            raise StudentError(404, "PROFILE_NOT_FOUND", "Student profile not found.")
        profile["skills"] = cur.execute(
            """
            SELECT s.skill_id AS id, s.name FROM student_skills ss
            JOIN skills s ON s.skill_id = ss.skill_id
            WHERE ss.student_id = %s ORDER BY s.name
            """,
            (student_id,),
        ).fetchall()
        profile["interests"] = cur.execute(
            """
            SELECT i.interest_id AS id, i.name FROM student_interests si
            JOIN interests i ON i.interest_id = si.interest_id
            WHERE si.student_id = %s ORDER BY i.name
            """,
            (student_id,),
        ).fetchall()
    profile["willing_to_relocate"] = bool(profile["willing_to_relocate"])
    profile["verified"] = bool(profile["verified"])
    profile["is_complete"] = bool(profile["is_complete"])
    return profile


def update_profile(conn, student_id: int, payload: dict) -> dict:
    try:
        year = int(payload.get("year_of_study"))
    except (TypeError, ValueError):
        raise StudentError(422, "INVALID_YEAR", "Choose a valid year of study.") from None
    if not 1 <= year <= 6:
        raise StudentError(422, "INVALID_YEAR", "Year of study must be between 1 and 6.")
    location = payload.get("preferred_location")
    if location is not None:
        location = _clean_text(location, "Preferred location", max_length=120, required=False) or None
    relocate = payload.get("willing_to_relocate", False)
    if not isinstance(relocate, bool):
        raise StudentError(422, "INVALID_INPUT", "Choose whether you are willing to relocate.")

    skills = _validated_id_list(payload.get("skills", []), "skills")
    interests = _validated_id_list(payload.get("interests", []), "interests")
    with conn.cursor() as cur:
        if skills:
            count = cur.execute("SELECT count(*) FROM skills WHERE skill_id = ANY(%s)", (skills,)).fetchone()[0]
            if count != len(skills):
                raise StudentError(422, "INVALID_SKILL", "Choose skills from the available list.")
        if interests:
            count = cur.execute("SELECT count(*) FROM interests WHERE interest_id = ANY(%s)", (interests,)).fetchone()[0]
            if count != len(interests):
                raise StudentError(422, "INVALID_INTEREST", "Choose interests from the available list.")
        cur.execute(
            """
            UPDATE student_profiles
            SET year_of_study = %s, preferred_location = %s,
                willing_to_relocate = %s
            WHERE student_id = %s
            """,
            (year, location, relocate, student_id),
        )
        cur.execute("DELETE FROM student_skills WHERE student_id = %s", (student_id,))
        cur.execute("DELETE FROM student_interests WHERE student_id = %s", (student_id,))
        if skills:
            cur.executemany(
                "INSERT INTO student_skills (student_id, skill_id) VALUES (%s, %s)",
                [(student_id, skill_id) for skill_id in skills],
            )
        if interests:
            cur.executemany(
                "INSERT INTO student_interests (student_id, interest_id) VALUES (%s, %s)",
                [(student_id, interest_id) for interest_id in interests],
            )
    return get_profile(conn, student_id)


def _validated_id_list(values: Any, label: str) -> list[int]:
    if not isinstance(values, list) or len(values) > 100:
        raise StudentError(422, "INVALID_INPUT", f"Choose valid {label}.")
    ids: list[int] = []
    for value in values:
        if isinstance(value, bool):
            raise StudentError(422, "INVALID_INPUT", f"Choose valid {label}.")
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise StudentError(422, "INVALID_INPUT", f"Choose valid {label}.") from None
        if number <= 0:
            raise StudentError(422, "INVALID_INPUT", f"Choose valid {label}.")
        if number not in ids:
            ids.append(number)
    return ids


def list_opportunities(conn, student_id: int, filters: dict[str, str]) -> dict:
    search = filters.get("search", "").strip()[:120]
    sector = filters.get("sector", "").strip()[:80]
    location = filters.get("location", "").strip()[:80]
    remote = filters.get("remote", "")
    try:
        min_weeks = int(filters["min_weeks"]) if filters.get("min_weeks") else None
        max_weeks = int(filters["max_weeks"]) if filters.get("max_weeks") else None
        page = int(filters.get("page", "1"))
        page_size = min(int(filters.get("page_size", "20")), 50)
    except ValueError:
        raise StudentError(422, "INVALID_FILTER", "Check the opportunity search filters.") from None
    if page < 1 or page_size < 1 or page_size > 50:
        raise StudentError(422, "INVALID_FILTER", "Check the opportunity page settings.")
    if min_weeks is not None and not 1 <= min_weeks <= 52:
        raise StudentError(422, "INVALID_FILTER", "Duration filters must be between 1 and 52 weeks.")
    if max_weeks is not None and not 1 <= max_weeks <= 52:
        raise StudentError(422, "INVALID_FILTER", "Duration filters must be between 1 and 52 weeks.")
    if remote not in ("", "true", "false"):
        raise StudentError(422, "INVALID_FILTER", "Check the remote filter.")

    clauses = ["TRUE"]
    params: list[Any] = [student_id]
    if search:
        clauses.append("v.search_vector @@ websearch_to_tsquery('english', %s)")
        params.append(search)
    if sector:
        clauses.append("v.sector ILIKE %s")
        params.append(f"%{sector}%")
    if location:
        clauses.append("v.location ILIKE %s")
        params.append(f"%{location}%")
    if remote:
        clauses.append("v.is_remote = %s")
        params.append(remote == "true")
    if min_weeks is not None:
        clauses.append("v.duration_weeks >= %s")
        params.append(min_weeks)
    if max_weeks is not None:
        clauses.append("v.duration_weeks <= %s")
        params.append(max_weeks)
    where = " AND ".join(clauses)
    count = conn.execute(
        f"SELECT count(*) FROM v_open_listings v WHERE {where}",
        params[1:],
    ).fetchone()[0]
    params.extend([page_size, (page - 1) * page_size])
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            f"""
            SELECT v.listing_id, v.title, v.description, v.company_name,
                   v.sector, v.location, v.is_remote, v.duration_weeks,
                   v.slots_remaining, v.application_deadline, v.required_skills,
                   v.accepted_programmes,
                   a.application_id, a.status AS application_status
            FROM v_open_listings v
            LEFT JOIN applications a
              ON a.listing_id = v.listing_id AND a.student_id = %s
            WHERE {where}
            ORDER BY v.application_deadline, v.listing_id
            LIMIT %s OFFSET %s
            """,
            params,
        ).fetchall()
    return {"results": rows, "count": int(count), "page": page, "page_size": page_size}


def list_applications(conn, student_id: int) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """
            SELECT a.application_id, a.listing_id, a.status, a.match_score,
                   a.cover_note, a.submitted_at, a.status_changed_at,
                   l.title, l.location, l.application_deadline,
                   c.name AS company_name, p.status AS placement_status
            FROM applications a
            JOIN listings l ON l.listing_id = a.listing_id
            JOIN companies c ON c.company_id = l.company_id
            LEFT JOIN placements p ON p.application_id = a.application_id
            WHERE a.student_id = %s
            ORDER BY a.submitted_at DESC, a.application_id DESC
            """,
            (student_id,),
        ).fetchall()


def submit_application(conn, user_id: int, student_id: int, payload: dict) -> dict:
    try:
        listing_id = int(payload.get("listing_id"))
    except (TypeError, ValueError):
        raise StudentError(422, "INVALID_LISTING", "Choose an opportunity to apply for.") from None
    if listing_id <= 0:
        raise StudentError(422, "INVALID_LISTING", "Choose an opportunity to apply for.")
    cover_note = payload.get("cover_note", "")
    if not isinstance(cover_note, str) or len(cover_note.strip()) > 2000:
        raise StudentError(422, "INVALID_COVER_NOTE", "Keep your cover note under 2,000 characters.")
    with conn.cursor(row_factory=dict_row) as cur:
        student = cur.execute(
            "SELECT verified FROM student_profiles WHERE student_id = %s FOR UPDATE",
            (student_id,),
        ).fetchone()
        if student is None:
            raise StudentError(404, "PROFILE_NOT_FOUND", "Student profile not found.")
        if not student["verified"]:
            raise StudentError(403, "STUDENT_NOT_VERIFIED", "A university coordinator must verify your profile before you can apply.")
        listing = cur.execute(
            "SELECT listing_id FROM v_open_listings WHERE listing_id = %s",
            (listing_id,),
        ).fetchone()
        if listing is None:
            raise StudentError(404, "OPPORTUNITY_UNAVAILABLE", "This opportunity is closed or no longer available.")
        score = cur.execute(
            """
            SELECT score FROM fn_recommendations(%s, 50)
            WHERE listing_id = %s
            """,
            (student_id, listing_id),
        ).fetchone()
        match_score = score["score"] if score else None
        cur.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))
        application = cur.execute(
            """
            INSERT INTO applications (student_id, listing_id, match_score, cover_note)
            VALUES (%s, %s, %s, %s)
            RETURNING application_id, status, submitted_at
            """,
            (student_id, listing_id, match_score, cover_note.strip() or None),
        ).fetchone()
    return application


def withdraw_application(conn, student_id: int, application_id: int) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        application = cur.execute(
            """
            UPDATE applications
            SET status = 'withdrawn'
            WHERE application_id = %s AND student_id = %s
              AND status IN ('submitted', 'under_review', 'shortlisted', 'accepted')
            RETURNING application_id, status
            """,
            (application_id, student_id),
        ).fetchone()
        if application is not None:
            return application
        existing = cur.execute(
            "SELECT status FROM applications WHERE application_id = %s AND student_id = %s",
            (application_id, student_id),
        ).fetchone()
    if existing is None:
        raise StudentError(404, "APPLICATION_NOT_FOUND", "Application not found.")
    raise StudentError(409, "APPLICATION_CANNOT_WITHDRAW", "This application can no longer be withdrawn.")


def list_notifications(conn, user_id: int) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """
            SELECT notification_id, title, message, is_read, created_at
            FROM notifications
            WHERE user_id = %s AND channel = 'in_app'
            ORDER BY created_at DESC, notification_id DESC
            LIMIT 50
            """,
            (user_id,),
        ).fetchall()


def mark_notification_read(conn, user_id: int, notification_id: int) -> dict:
    if notification_id <= 0:
        raise StudentError(422, "INVALID_NOTIFICATION", "Notification id must be positive.")
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            """
            UPDATE notifications
            SET is_read = true, read_at = now()
            WHERE notification_id = %s AND user_id = %s AND channel = 'in_app'
            RETURNING notification_id
            """,
            (notification_id, user_id),
        ).fetchone()
        if row is None:
            raise StudentError(404, "NOTIFICATION_NOT_FOUND", "Notification not found.")
    return {"notification_id": int(row["notification_id"]), "is_read": True}
