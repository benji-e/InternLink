"""Inviting university coordinators by email.

An administrator (for any verified university) or a university-wide
coordinator (for their own university) invites a colleague. That creates a
pending coordinator account plus a one-time link. The colleague opens the
link, sets their name and password, and the account is active straight away:
the link proves they own the email address.
"""

from __future__ import annotations

import secrets
from typing import Any

from psycopg.rows import dict_row

from .accounts import _bcrypt_hash, _check_password, _clean_email, _issue_token, _token_hash
from .service import StudentError, _clean_text

INVITE_DAYS = 7


def _university(cur, university_id: int) -> dict:
    university = cur.execute(
        "SELECT university_id, name, email_domain, status FROM universities WHERE university_id = %s",
        (university_id,),
    ).fetchone()
    if university is None:
        raise StudentError(404, "UNIVERSITY_NOT_FOUND", "University not found.")
    if university["status"] != "verified":
        raise StudentError(409, "UNIVERSITY_NOT_VERIFIED", "Verify the university before inviting coordinators.")
    return university


def invite_coordinator(conn, university_id: int, payload: dict, raw_token: str, *, inviter_name: str) -> dict:
    """Create (or refresh) an invite. Returns what the caller needs to send the email."""

    email = _clean_email(payload.get("email"))
    department_id: Any = payload.get("department_id")
    if department_id in (None, ""):
        department_id = None
    else:
        try:
            department_id = int(department_id)
        except (TypeError, ValueError):
            raise StudentError(422, "INVALID_INPUT", "Choose a department.") from None
    with conn.cursor(row_factory=dict_row) as cur:
        university = _university(cur, university_id)
        domain = university["email_domain"]
        email_domain = email.rsplit("@", 1)[1]
        if email_domain != domain and not email_domain.endswith(f".{domain}"):
            raise StudentError(422, "UNIVERSITY_EMAIL_REQUIRED", f"Coordinators need an email address ending in {domain}.")
        if department_id is not None and not cur.execute(
            "SELECT 1 FROM departments WHERE department_id = %s AND university_id = %s", (department_id, university_id)
        ).fetchone():
            raise StudentError(404, "DEPARTMENT_NOT_FOUND", "Department not found at this university.")

        existing = cur.execute(
            "SELECT user_id, role, status, university_id, email_verified_at FROM users WHERE lower(email) = %s FOR UPDATE",
            (email,),
        ).fetchone()
        if existing is not None:
            invited_before = (
                existing["role"] == "coordinator" and existing["university_id"] == university_id
                and existing["status"] == "pending" and existing["email_verified_at"] is None
            )
            if not invited_before:
                raise StudentError(409, "ALREADY_EXISTS", "Someone already has an InternLink account with that email.")
            user_id = existing["user_id"]
            cur.execute("UPDATE users SET department_id = %s WHERE user_id = %s", (department_id, user_id))
        else:
            user_id = cur.execute(
                """
                INSERT INTO users (email, password_hash, full_name, role, status, university_id, department_id)
                VALUES (%s, %s, %s, 'coordinator', 'pending', %s, %s) RETURNING user_id
                """,
                # Nobody knows this password; the invite link sets the real one.
                (email, _bcrypt_hash(secrets.token_urlsafe(32)), email.split("@", 1)[0], university_id, department_id),
            ).fetchone()["user_id"]
        if not _issue_token(cur, user_id, "coordinator_invite", raw_token, f"interval '{INVITE_DAYS} days'"):
            raise StudentError(429, "INVITE_RECENTLY_SENT", "An invite was sent to that address a moment ago.")
    return {"email": email, "university": university["name"], "inviter": inviter_name, "days": INVITE_DAYS}


def _open_invite(cur, raw_token: Any, *, lock: bool = False) -> dict:
    if not isinstance(raw_token, str) or not raw_token.strip():
        raise StudentError(400, "INVALID_INVITE", "This invite link is invalid or has expired.")
    row = cur.execute(
        f"""
        SELECT t.token_id, u.user_id, u.email, u.status, un.name AS university, un.status AS university_status,
               d.name AS department
        FROM auth_tokens t
        JOIN users u ON u.user_id = t.user_id
        JOIN universities un ON un.university_id = u.university_id
        LEFT JOIN departments d ON d.department_id = u.department_id
        WHERE t.token_hash = %s AND t.purpose = 'coordinator_invite'
          AND t.used_at IS NULL AND t.revoked_at IS NULL AND t.expires_at > now()
        {"FOR UPDATE OF t, u" if lock else ""}
        """,
        (_token_hash(raw_token.strip()),),
    ).fetchone()
    if row is None or row["status"] != "pending" or row["university_status"] != "verified":
        raise StudentError(400, "INVALID_INVITE", "This invite link is invalid or has expired.")
    return row


def invite_details(conn, raw_token: Any) -> dict:
    """What the accept page shows: who the invite is for."""
    with conn.cursor(row_factory=dict_row) as cur:
        row = _open_invite(cur, raw_token)
    return {"email": row["email"], "university": row["university"], "department": row["department"]}


def accept_invite(conn, raw_token: Any, payload: dict) -> dict:
    full_name = _clean_text(payload.get("full_name"), "Full name", max_length=160)
    password = _check_password(payload.get("password"), "coordinator")
    with conn.cursor(row_factory=dict_row) as cur:
        row = _open_invite(cur, raw_token, lock=True)
        cur.execute("UPDATE auth_tokens SET used_at = now() WHERE token_id = %s", (row["token_id"],))
        cur.execute(
            """
            UPDATE users SET full_name = %s, password_hash = %s, status = 'active',
                   email_verified_at = now(), failed_login_count = 0, locked_until = NULL
            WHERE user_id = %s
            """,
            (full_name, _bcrypt_hash(password), row["user_id"]),
        )
    return {"email": row["email"], "message": "Your coordinator account is ready. You can sign in now."}


def list_coordinators(conn, university_id: int) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """
            SELECT u.user_id, u.full_name, u.email, u.status, d.name AS department,
                   (u.status = 'pending' AND u.email_verified_at IS NULL
                    AND EXISTS (SELECT 1 FROM auth_tokens t WHERE t.user_id = u.user_id AND t.purpose = 'coordinator_invite')) AS invited,
                   u.created_at
            FROM users u LEFT JOIN departments d ON d.department_id = u.department_id
            WHERE u.role = 'coordinator' AND u.university_id = %s
            ORDER BY u.status = 'active' DESC, u.full_name
            """,
            (university_id,),
        ).fetchall()


def list_verified_universities(conn) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """
            SELECT un.university_id, un.name, un.location, un.email_domain,
                   count(u.user_id) FILTER (WHERE u.status = 'active') AS active_coordinators,
                   count(u.user_id) FILTER (WHERE u.status = 'pending') AS pending_coordinators,
                   (SELECT count(*) FROM student_profiles sp WHERE sp.university_id = un.university_id) AS students
            FROM universities un
            LEFT JOIN users u ON u.university_id = un.university_id AND u.role = 'coordinator'
            WHERE un.status = 'verified'
            GROUP BY un.university_id ORDER BY un.name
            """
        ).fetchall()
