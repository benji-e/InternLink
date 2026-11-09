"""Self-service account flows shared by every role.

University registration, resending the verification email, and password
reset. Each function works inside the caller's transaction and never sends
email itself: it returns what the caller needs to send one, so the HTTP layer
decides how to deliver it.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

import bcrypt
from psycopg.rows import dict_row

from employer_module.internlink_employer.security import hash_password as hash_employer_password

from .service import EMAIL_RE, StudentError, _clean_text

DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}$")
VERIFY_HOURS = 24
RESET_MINUTES = 60
# A second email of the same kind within this window is silently skipped.
RESEND_COOLDOWN_SECONDS = 60
# Roles that sign themselves up and confirm their email with a link.
SELF_SERVICE_ROLES = ("student", "employer", "coordinator")
GENERIC_EMAIL_MESSAGE = "If an account matches that email, we've sent it a link."


def _token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _clean_email(value: Any) -> str:
    email = _clean_text(value, "Email", max_length=254).lower()
    if not EMAIL_RE.fullmatch(email):
        raise StudentError(422, "INVALID_EMAIL", "Enter a valid email address.")
    return email


def _bcrypt_hash(password: str) -> str:
    try:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")
    except ValueError:
        raise StudentError(422, "WEAK_PASSWORD", "Use a password of at most 72 UTF-8 bytes.") from None


def _check_password(password: Any, role: str) -> str:
    if not isinstance(password, str) or len(password) < 10:
        raise StudentError(422, "WEAK_PASSWORD", "Use a password with at least 10 characters.")
    if len(password.encode("utf-8")) > 72:
        raise StudentError(422, "WEAK_PASSWORD", "Use a password of at most 72 UTF-8 bytes.")
    if role == "employer" and not (
        re.search("[A-Z]", password) and re.search("[a-z]", password) and re.search(r"\d", password)
    ):
        raise StudentError(
            422, "WEAK_PASSWORD",
            "Employer passwords need upper and lower case letters and a digit.",
        )
    return password


def register_university(conn, payload: dict, verification_token: str) -> dict:
    """Create a pending university and its first (pending) coordinator account.

    The coordinator confirms their email; the account becomes active once an
    administrator verifies the university.
    """

    name = _clean_text(payload.get("university_name"), "University name", max_length=200)
    location = _clean_text(payload.get("location"), "Location", max_length=150)
    domain = _clean_text(payload.get("email_domain"), "Email domain", max_length=120).lower()
    domain = domain.removeprefix("@")
    if not DOMAIN_RE.fullmatch(domain):
        raise StudentError(422, "INVALID_DOMAIN", "Enter the university's email domain, for example must.ac.ug.")
    full_name = _clean_text(payload.get("full_name"), "Full name", max_length=160)
    email = _clean_email(payload.get("email"))
    email_domain = email.rsplit("@", 1)[1]
    if email_domain != domain and not email_domain.endswith(f".{domain}"):
        raise StudentError(
            422, "UNIVERSITY_EMAIL_REQUIRED",
            f"Use your staff email address at {domain}.",
        )
    password_hash = _bcrypt_hash(_check_password(payload.get("password"), "coordinator"))

    with conn.cursor(row_factory=dict_row) as cur:
        existing = cur.execute(
            "SELECT status FROM universities WHERE lower(name) = lower(%s) OR lower(email_domain) = %s",
            (name, domain),
        ).fetchone()
        if existing is not None:
            raise StudentError(
                409, "UNIVERSITY_EXISTS",
                "That university is already registered or waiting for review. "
                "Ask your administrator to add you as a coordinator.",
            )
        university = cur.execute(
            """
            INSERT INTO universities (name, location, email_domain)
            VALUES (%s, %s, %s)
            RETURNING university_id
            """,
            (name, location, domain),
        ).fetchone()
        user = cur.execute(
            """
            INSERT INTO users (email, password_hash, full_name, role, status, university_id)
            VALUES (%s, %s, %s, 'coordinator', 'pending', %s)
            RETURNING user_id
            """,
            (email, password_hash, full_name, university["university_id"]),
        ).fetchone()
        cur.execute(
            """
            INSERT INTO auth_tokens (user_id, purpose, token_hash, expires_at)
            VALUES (%s, 'email_verify', %s, now() + make_interval(hours => %s))
            """,
            (user["user_id"], _token_hash(verification_token), VERIFY_HOURS),
        )
    return {
        "university_id": int(university["university_id"]),
        "user_id": int(user["user_id"]),
        "email": email,
        "full_name": full_name,
    }


def verify_account_email(conn, verification_token: str) -> dict:
    """Consume an email-verification link for a student or coordinator.

    Students become active straight away. Coordinators become active only when
    their university is already verified; otherwise they wait for the admin.
    """

    with conn.cursor(row_factory=dict_row) as cur:
        token = cur.execute(
            """
            SELECT t.token_id, t.user_id, u.role, un.status AS university_status
            FROM auth_tokens t
            JOIN users u ON u.user_id = t.user_id
            LEFT JOIN universities un ON un.university_id = u.university_id
            WHERE t.token_hash = %s AND t.purpose = 'email_verify'
              AND t.used_at IS NULL AND t.revoked_at IS NULL
              AND t.expires_at > now()
            FOR UPDATE OF t, u
            """,
            (_token_hash(verification_token),),
        ).fetchone()
        if token is None or token["role"] not in ("student", "coordinator"):
            raise StudentError(400, "INVALID_VERIFICATION_TOKEN", "This verification link is invalid or expired.")
        activate = token["role"] == "student" or token["university_status"] == "verified"
        cur.execute("UPDATE auth_tokens SET used_at = now() WHERE token_id = %s", (token["token_id"],))
        cur.execute(
            """
            UPDATE users
            SET email_verified_at = now(),
                status = CASE WHEN %s AND status = 'pending' THEN 'active' ELSE status END,
                failed_login_count = 0, locked_until = NULL
            WHERE user_id = %s
            """,
            (activate, token["user_id"]),
        )
    return {"verified": True, "role": token["role"], "awaiting_review": not activate}



def activate_university_coordinators(conn, university_id: int) -> int:
    """After an admin verifies a university, activate its confirmed coordinators."""

    cursor = conn.execute(
        """
        UPDATE users SET status = 'active'
        WHERE university_id = %s AND role = 'coordinator'
          AND status = 'pending' AND email_verified_at IS NOT NULL
        """,
        (university_id,),
    )
    return cursor.rowcount


def _issue_token(cur, user_id: int, purpose: str, raw_token: str, interval_sql: str) -> bool:
    """Replace a user's open tokens of one purpose; False while in cooldown."""

    recent = cur.execute(
        """
        SELECT 1 FROM auth_tokens
        WHERE user_id = %s AND purpose = %s
          AND created_at > now() - make_interval(secs => %s)
        """,
        (user_id, purpose, RESEND_COOLDOWN_SECONDS),
    ).fetchone()
    if recent is not None:
        return False
    # Expire as well as revoke: the employer module's verify check reads only
    # used_at/expires_at. Every open token here is older than the cooldown,
    # so now() stays after created_at.
    cur.execute(
        """
        UPDATE auth_tokens SET revoked_at = now(), expires_at = now()
        WHERE user_id = %s AND purpose = %s AND used_at IS NULL AND revoked_at IS NULL
          AND expires_at > now()
        """,
        (user_id, purpose),
    )
    cur.execute(
        f"""
        INSERT INTO auth_tokens (user_id, purpose, token_hash, expires_at)
        VALUES (%s, %s, %s, now() + {interval_sql})
        """,
        (user_id, purpose, _token_hash(raw_token)),
    )
    return True


def create_email_verification(conn, email: Any, raw_token: str) -> dict | None:
    """Issue a fresh verification link for an unverified account.

    Returns the recipient details, or None when there is nothing to send (no
    such account, already verified, or a link was sent moments ago). Callers
    must answer the same way in every case so emails can't be probed.
    """

    try:
        email = _clean_email(email)
    except StudentError:
        return None
    with conn.cursor(row_factory=dict_row) as cur:
        user = cur.execute(
            """
            SELECT user_id, email, full_name, role FROM users
            WHERE lower(email) = %s AND status = 'pending'
              AND email_verified_at IS NULL AND role = ANY(%s)
            FOR UPDATE
            """,
            (email, list(SELF_SERVICE_ROLES)),
        ).fetchone()
        if user is None:
            return None
        if not _issue_token(cur, user["user_id"], "email_verify", raw_token, f"interval '{VERIFY_HOURS} hours'"):
            return None
    return {"email": user["email"], "full_name": user["full_name"], "role": user["role"]}


def create_password_reset(conn, email: Any, raw_token: str) -> dict | None:
    """Issue a one-hour password-reset link. Same no-leak contract as above."""

    try:
        email = _clean_email(email)
    except StudentError:
        return None
    with conn.cursor(row_factory=dict_row) as cur:
        user = cur.execute(
            """
            SELECT user_id, email, full_name, role FROM users
            WHERE lower(email) = %s AND status IN ('active', 'pending')
            FOR UPDATE
            """,
            (email,),
        ).fetchone()
        if user is None:
            return None
        if not _issue_token(cur, user["user_id"], "password_reset", raw_token, f"interval '{RESET_MINUTES} minutes'"):
            return None
    return {"email": user["email"], "full_name": user["full_name"], "role": user["role"]}


def reset_password(conn, raw_token: Any, new_password: Any) -> dict:
    """Set a new password from a reset link and sign out other sessions."""

    if not isinstance(raw_token, str) or not raw_token.strip():
        raise StudentError(400, "INVALID_RESET_TOKEN", "This reset link is invalid or expired.")
    with conn.cursor(row_factory=dict_row) as cur:
        token = cur.execute(
            """
            SELECT t.token_id, t.user_id, u.role, u.status
            FROM auth_tokens t
            JOIN users u ON u.user_id = t.user_id
            WHERE t.token_hash = %s AND t.purpose = 'password_reset'
              AND t.used_at IS NULL AND t.revoked_at IS NULL
              AND t.expires_at > now()
            FOR UPDATE OF t, u
            """,
            (_token_hash(raw_token.strip()),),
        ).fetchone()
        if token is None or token["status"] not in ("active", "pending"):
            raise StudentError(400, "INVALID_RESET_TOKEN", "This reset link is invalid or expired.")
        password = _check_password(new_password, token["role"])
        password_hash = (
            hash_employer_password(password) if token["role"] == "employer" else _bcrypt_hash(password)
        )
        cur.execute("UPDATE auth_tokens SET used_at = now() WHERE token_id = %s", (token["token_id"],))
        cur.execute(
            """
            UPDATE auth_tokens SET revoked_at = now()
            WHERE user_id = %s AND token_id <> %s AND purpose IN ('password_reset', 'refresh')
              AND used_at IS NULL AND revoked_at IS NULL
            """,
            (token["user_id"], token["token_id"]),
        )
        cur.execute(
            """
            UPDATE users SET password_hash = %s, failed_login_count = 0, locked_until = NULL
            WHERE user_id = %s
            """,
            (password_hash, token["user_id"]),
        )
    return {"reset": True, "awaiting_verification": token["status"] == "pending"}
