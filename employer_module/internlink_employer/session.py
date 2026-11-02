"""Session construction from a verified bearer token (Auth module 4.2.1)."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ModuleError, RULE_MAP


@dataclass(frozen=True)
class Session:
    user_id: int
    role: str
    status: str
    company_id: int


def _deny(db, message: str):
    db.set_actor(None)
    db.log_event("access_denied", result="denied")
    raise ModuleError("forbidden", message)


def open_session(db, auth_service, token: str | None) -> Session:
    """Verify the token, load the user and enforce employer/account rules.

    ``company_id`` is always read from the database, never from caller input.
    """

    claims = auth_service.verify_token(token)
    if not claims:
        raise ModuleError("unauthenticated", "Please log in again.")
    try:
        user_id = int(claims.get("user_id"))
    except (TypeError, ValueError):
        raise ModuleError("unauthenticated", "Please log in again.") from None
    if user_id <= 0:
        raise ModuleError("unauthenticated", "Please log in again.")

    user = db.query_one(
        "SELECT user_id, role, status, company_id FROM users WHERE user_id = %s",
        [user_id],
    )
    if user is None or user["role"] != "employer":
        _deny(db, "Employer access only.")

    if user["status"] != "active":
        _deny(db, RULE_MAP["RULE_ACCOUNT_NOT_ACTIVE"][1])

    if user["company_id"] is None:
        _deny(db, "Your employer account is not linked to a company.")

    return Session(
        user_id=int(user["user_id"]),
        role="employer",
        status=str(user["status"]),
        company_id=int(user["company_id"]),
    )
