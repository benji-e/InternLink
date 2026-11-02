"""Module errors and translation of database integrity errors.

The service layer never exposes HTTP details.  It raises :class:`ModuleError`
with a category (invalid, forbidden, not_found, conflict, unauthenticated) and
the API/handler layer maps that category to a transport status code.
"""

from __future__ import annotations


CATEGORIES = ("invalid", "forbidden", "not_found", "conflict", "unauthenticated")


class ModuleError(Exception):
    """A business-rule failure that is safe to show to the caller."""

    def __init__(self, category: str, message: str, fields: dict | None = None):
        if category not in CATEGORIES:
            raise ValueError(f"unknown error category: {category}")
        super().__init__(message)
        self.category = category
        self.message = message
        self.fields = fields or {}

    def as_dict(self) -> dict:
        return {
            "ok": False,
            "category": self.category,
            "message": self.message,
            "fields": self.fields,
        }


# DB rule codes (design doc section 6) -> (category, friendly message).
RULE_MAP = {
    "RULE_SR07_COMPANY_NOT_VERIFIED": (
        "forbidden",
        "Your company must be verified by an administrator first.",
    ),
    "RULE_SR08_DEADLINE_PAST": (
        "invalid",
        "The application deadline must be today or later.",
    ),
    "RULE_LISTING_TRANSITION": (
        "conflict",
        "That change of listing status is not allowed.",
    ),
    "RULE_SR04_TRANSITION": (
        "conflict",
        "That change of application status is not allowed.",
    ),
    "RULE_SR10_NOT_SHORTLISTED": (
        "conflict",
        "You can only message shortlisted or accepted candidates.",
    ),
    "RULE_SR10_PARTIES": (
        "forbidden",
        "Messages are only allowed between you and the candidate.",
    ),
    "RULE_SR11_NOT_OWNER": (
        "forbidden",
        "Only an employer of the host company can complete this placement.",
    ),
    "RULE_SR11_NOT_ENDED": (
        "conflict",
        "A placement can only be completed after its end date.",
    ),
    "RULE_SR17_OWNERSHIP": (
        "forbidden",
        "The owning company of a listing cannot be changed.",
    ),
    "RULE_ACCOUNT_NOT_ACTIVE": (
        "forbidden",
        "Your account is not active.",
    ),
}


class DatabaseIntegrityError(Exception):
    """Normalised integrity error raised by the database adapters.

    Mirrors the attributes the design document expects: ``message`` starts with
    the rule code when the database raises one (for example a trigger using
    ``RAISE(ABORT, 'RULE_SR04_TRANSITION: ...')``), and ``constraint_name`` is
    the name of the violated constraint when the driver exposes it.
    """

    def __init__(self, message: str, constraint_name: str | None = None):
        super().__init__(message)
        self.message = message
        self.constraint_name = constraint_name or ""


def translate_db_error(err: DatabaseIntegrityError) -> ModuleError:
    """Turn a database integrity error into a caller-safe ModuleError."""

    code = (err.message or "").split(":", 1)[0].strip()
    if code in RULE_MAP:
        return ModuleError(*RULE_MAP[code])

    constraint = err.constraint_name or ""
    if constraint.startswith("ck_"):
        return ModuleError("invalid", "A field value is outside the allowed range.")
    if constraint.startswith("uq_"):
        return ModuleError("conflict", "That record already exists.")
    if constraint.startswith("fk_"):
        return ModuleError("invalid", "A referenced record does not exist.")
    if constraint.startswith("nn_"):
        return ModuleError("invalid", "A required value is missing.")
    return ModuleError("conflict", "The request conflicts with current data.")
