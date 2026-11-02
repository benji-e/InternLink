"""Company registration, email verification and profile services."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta

from ..errors import DatabaseIntegrityError, ModuleError, translate_db_error
from ..security import hash_password, hash_token, new_token, verification_link
from ..session import Session
from ..validation import prepare_company_update, prepare_registration
from .common import run_write, utcnow

BANNERS = {
    "pending": "Awaiting administrator verification. You cannot publish listings yet.",
    "suspended": "Your company has been suspended. Contact the administrator.",
}


def register_employer(db, mailer, form: Mapping, *, base_url: str = "http://localhost:8000") -> dict:
    """Create a pending company, its employer user and an email-verify token."""

    if not isinstance(form, Mapping):
        raise ModuleError("invalid", "Please correct the form.", {"form": "Invalid"})
    clean, errors = prepare_registration(form)
    if errors:
        raise ModuleError("invalid", "Please correct the form.", errors)

    password_hash = hash_password(clean["password"])  # plain password never stored (NFR04)
    raw_token = new_token()
    token_hash = hash_token(raw_token)
    expires_at = utcnow() + timedelta(hours=24)

    try:
        with db.transaction():
            company_id = db.insert_returning_id(
                "companies",
                {
                    "name": clean["company_name"],
                    "sector": clean["sector"],
                    "location": clean["location"],
                    "description": clean["description"],
                    "contact_email": clean["contact_email"],
                    "website": clean["website"],
                },
            )
            user_id = db.insert_returning_id(
                "users",
                {
                    "email": clean["rep_email"],
                    "password_hash": password_hash,
                    "full_name": clean["rep_full_name"],
                    "phone": clean["rep_phone"],
                    "role": "employer",
                    "company_id": company_id,
                },
            )
            db.insert(
                "auth_tokens",
                {
                    "user_id": user_id,
                    "purpose": "email_verify",
                    "token_hash": token_hash,
                    "expires_at": expires_at,
                },
            )
            mailer.send(
                clean["rep_email"],
                "Verify your email",
                verification_link(base_url, raw_token),
            )
    except DatabaseIntegrityError as err:
        raise translate_db_error(err) from err

    return {
        "company_id": company_id,
        "message": "Check your email. After that an administrator will verify your company.",
    }


def verify_employer_email(db, raw_token: str | None) -> dict:
    """Consume a one-time verification token and activate the employer user."""

    if not raw_token or not isinstance(raw_token, str):
        raise ModuleError("invalid", "The link is invalid or has expired.")
    token_hash = hash_token(raw_token)
    now = utcnow()
    token = db.query_one(
        """
        SELECT * FROM auth_tokens
        WHERE token_hash = %s AND purpose = 'email_verify'
          AND used_at IS NULL AND expires_at > %s
        """,
        [token_hash, now],
    )
    if token is None:
        raise ModuleError("invalid", "The link is invalid or has expired.")

    try:
        with db.transaction():
            db.set_actor(int(token["user_id"]))
            consumed = db.execute(
                """
                UPDATE auth_tokens SET used_at = %s
                WHERE token_id = %s AND used_at IS NULL
                """,
                [now, token["token_id"]],
            )
            if consumed != 1:
                raise ModuleError("invalid", "The link is invalid or has expired.")
            db.execute(
                """
                UPDATE users
                SET email_verified_at = %s,
                    status = CASE WHEN status = 'pending' THEN 'active' ELSE status END
                WHERE user_id = %s
                """,
                [now, token["user_id"]],
            )
            db.log_event(
                "employer_email_verified",
                "users",
                token["user_id"],
                result="success",
            )
    finally:
        db.set_actor(None)
    return {
        "message": "Email verified. Your company now awaits administrator approval (task 4.7.2)."
    }


def get_company_status(db, session: Session) -> dict:
    company = db.query_one(
        """
        SELECT company_id, name, sector, location, description, contact_email, website,
               verification_status, rejection_reason, verified_at
        FROM companies WHERE company_id = %s
        """,
        [session.company_id],
    )
    if company is None:
        raise ModuleError("not_found", "Company not found.")

    status = company["verification_status"]
    banner = BANNERS.get(status)
    if status == "rejected":
        reason = (company.get("rejection_reason") or "No reason provided.").strip()
        banner = f"Not verified. Reason: {reason}"

    return {
        "company": company,
        "can_publish": status == "verified",
        "banner": banner,
    }


def update_company_profile(db, session: Session, form: Mapping) -> dict:
    """Update employer-editable company fields; name/verification stay admin-only."""

    if not isinstance(form, Mapping):
        raise ModuleError("invalid", "Please correct the form.", {"form": "Invalid"})
    clean, errors = prepare_company_update(form)
    if errors:
        raise ModuleError("invalid", "Please correct the form.", errors)

    def action():
        db.execute(
            """
            UPDATE companies
            SET sector = %s, location = %s, description = %s,
                contact_email = %s, website = %s
            WHERE company_id = %s
            """,
            [
                clean["sector"],
                clean["location"],
                clean["description"],
                clean["contact_email"],
                clean["website"],
                session.company_id,
            ],
        )
        db.log_event("company_profile_updated", "companies", session.company_id, result="success")

    run_write(db, session, action)
    return get_company_status(db, session)
