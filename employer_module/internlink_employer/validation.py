"""Input cleaning and validation for registration, company and listing forms.

Validation returns field-keyed messages so the UI can highlight the exact input
that failed.  Cleaning happens before validation so services never have to deal
with untrusted JSON value types (for example ``"7"`` versus ``7``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime

from .constants import SLOTS_RANGE, WEEKS_RANGE

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

REGISTRATION_REQUIRED = (
    "company_name",
    "sector",
    "location",
    "contact_email",
    "rep_full_name",
    "rep_email",
    "password",
)

MAX_LENGTHS = {
    "company_name": 150,
    "sector": 100,
    "location": 150,
    "contact_email": 254,
    "website": 500,
    "description": 5000,
    "rep_full_name": 150,
    "rep_email": 254,
    "rep_phone": 30,
    "password": 256,
    "title": 150,
    "listing_description": 10_000,
}

LISTING_REQUIRED = ("title", "description", "sector", "location")
LISTING_TEXT_LIMITS = {
    "title": MAX_LENGTHS["title"],
    "description": MAX_LENGTHS["listing_description"],
    "sector": MAX_LENGTHS["sector"],
    "location": MAX_LENGTHS["location"],
}


def _clean_text(value, *, max_length: int, errors: dict, key: str, required: bool):
    if value is None:
        if required:
            errors[key] = "Required"
        return None
    if not isinstance(value, str):
        errors[key] = "Invalid value"
        return None
    cleaned = value.strip()
    if required and not cleaned:
        errors[key] = "Required"
        return None
    if len(cleaned) > max_length:
        errors[key] = f"Must be at most {max_length} characters"
        return None
    return cleaned or None


def _clean_email(value, *, errors: dict, key: str, required: bool):
    cleaned = _clean_text(
        value, max_length=MAX_LENGTHS["contact_email"], errors=errors, key=key, required=required
    )
    if cleaned is not None and not EMAIL_RE.match(cleaned):
        errors[key] = "Invalid email"
        return None
    return cleaned.lower() if cleaned else None


def _coerce_int(value) -> int | None:
    """Strict integer coercion: reject bools and non-integral JSON numbers."""

    if isinstance(value, bool) or value is None or value == "":
        return None
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not re.fullmatch(r"[+-]?\d+", text):
            return None
        return int(text)
    return None


def _clean_int(value, *, errors: dict, key: str):
    number = _coerce_int(value)
    if number is None:
        errors[key] = "Enter a whole number"
        return None
    return number


def _clean_id_list(value, *, errors: dict, key: str):
    if value in (None, "", []):
        return []
    if not isinstance(value, (list, tuple, set)):
        errors[key] = "Expected a list"
        return []
    result: list[int] = []
    seen: set[int] = set()
    for item in value:
        number = _coerce_int(item)
        if number is None or number <= 0:
            errors[key] = "Unknown value"
            return []
        if number not in seen:
            seen.add(number)
            result.append(number)
    return result


def _clean_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _clean_deadline(value, *, errors: dict):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str) or not value.strip():
        errors["application_deadline"] = "Invalid date"
        return None
    text = value.strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        errors["application_deadline"] = "Invalid date"
        return None


def prepare_registration(form: Mapping) -> tuple[dict, dict]:
    """Return ``(clean_values, field_errors)`` for employer registration."""

    errors: dict[str, str] = {}
    clean: dict[str, object] = {}

    for field in REGISTRATION_REQUIRED:
        if not isinstance(form.get(field), str) or not form.get(field, "").strip():
            errors[field] = "Required"

    clean["company_name"] = _clean_text(
        form.get("company_name"), max_length=MAX_LENGTHS["company_name"],
        errors=errors, key="company_name", required=True,
    )
    clean["sector"] = _clean_text(
        form.get("sector"), max_length=MAX_LENGTHS["sector"],
        errors=errors, key="sector", required=True,
    )
    clean["location"] = _clean_text(
        form.get("location"), max_length=MAX_LENGTHS["location"],
        errors=errors, key="location", required=True,
    )
    clean["description"] = _clean_text(
        form.get("description"), max_length=MAX_LENGTHS["description"],
        errors=errors, key="description", required=False,
    )
    clean["website"] = _clean_text(
        form.get("website"), max_length=MAX_LENGTHS["website"],
        errors=errors, key="website", required=False,
    )
    clean["contact_email"] = _clean_email(
        form.get("contact_email"), errors=errors, key="contact_email", required=True
    )
    clean["rep_full_name"] = _clean_text(
        form.get("rep_full_name"), max_length=MAX_LENGTHS["rep_full_name"],
        errors=errors, key="rep_full_name", required=True,
    )
    clean["rep_email"] = _clean_email(
        form.get("rep_email"), errors=errors, key="rep_email", required=True
    )
    clean["rep_phone"] = _clean_text(
        form.get("rep_phone"), max_length=MAX_LENGTHS["rep_phone"],
        errors=errors, key="rep_phone", required=False,
    )

    password = form.get("password")
    if not isinstance(password, str) or not password:
        errors["password"] = "Required"
        clean["password"] = None
    elif len(password) > MAX_LENGTHS["password"]:
        errors["password"] = f"Must be at most {MAX_LENGTHS['password']} characters"
        clean["password"] = None
    elif (
        len(password) < 8
        or not re.search("[A-Z]", password)
        or not re.search("[a-z]", password)
        or not re.search(r"\d", password)
    ):
        errors["password"] = "At least 8 characters with upper, lower case and a digit"
        clean["password"] = None
    else:
        clean["password"] = password

    return clean, errors


def validate_registration(form: Mapping) -> dict:
    """Compatibility helper: return only the field errors."""

    return prepare_registration(form)[1]


def prepare_company_update(form: Mapping) -> tuple[dict, dict]:
    """Only the fields employers may edit; name/verification stay admin-only."""

    errors: dict[str, str] = {}
    clean = {
        "sector": _clean_text(
            form.get("sector"), max_length=MAX_LENGTHS["sector"],
            errors=errors, key="sector", required=True,
        ),
        "location": _clean_text(
            form.get("location"), max_length=MAX_LENGTHS["location"],
            errors=errors, key="location", required=True,
        ),
        "description": _clean_text(
            form.get("description"), max_length=MAX_LENGTHS["description"],
            errors=errors, key="description", required=False,
        ),
        "contact_email": _clean_email(
            form.get("contact_email"), errors=errors, key="contact_email", required=True
        ),
        "website": _clean_text(
            form.get("website"), max_length=MAX_LENGTHS["website"],
            errors=errors, key="website", required=False,
        ),
    }
    return clean, errors


def clean_listing_form(form: Mapping) -> tuple[dict, dict]:
    """Clean types and return field errors for a listing form."""

    errors: dict[str, str] = {}
    clean: dict[str, object] = {}

    for field in LISTING_REQUIRED:
        clean[field] = _clean_text(
            form.get(field), max_length=LISTING_TEXT_LIMITS[field],
            errors=errors, key=field, required=True,
        )

    clean["is_remote"] = _clean_bool(form.get("is_remote", False))
    clean["duration_weeks"] = _clean_int(
        form.get("duration_weeks"), errors=errors, key="duration_weeks"
    )
    clean["slots"] = _clean_int(form.get("slots"), errors=errors, key="slots")
    clean["application_deadline"] = _clean_deadline(
        form.get("application_deadline"), errors=errors
    )

    for key in ("required_skill_ids", "optional_skill_ids", "programme_ids", "interest_ids"):
        clean[key] = _clean_id_list(form.get(key), errors=errors, key=key)

    required_skills = set(clean.get("required_skill_ids") or ())
    optional_skills = set(clean.get("optional_skill_ids") or ())
    if required_skills & optional_skills:
        errors["optional_skill_ids"] = "A skill cannot be both required and optional"

    duration = clean.get("duration_weeks")
    if duration is not None and not (WEEKS_RANGE[0] <= duration <= WEEKS_RANGE[1]):
        errors["duration_weeks"] = f"{WEEKS_RANGE[0]} to {WEEKS_RANGE[1]}"

    slots = clean.get("slots")
    if slots is not None and not (SLOTS_RANGE[0] <= slots <= SLOTS_RANGE[1]):
        errors["slots"] = f"{SLOTS_RANGE[0]} to {SLOTS_RANGE[1]}"

    return clean, errors


def prepare_listing(db, form: Mapping) -> tuple[dict, dict]:
    """Clean a listing and verify all tag ids exist in the controlled vocabularies."""

    clean, errors = clean_listing_form(form)
    for key, table in (
        ("required_skill_ids", "skills"),
        ("optional_skill_ids", "skills"),
        ("programme_ids", "programmes"),
        ("interest_ids", "interests"),
    ):
        if key in errors:
            continue
        ids = clean.get(key) or []
        if ids and db.count_existing(table, ids) != len(set(ids)):
            errors[key] = "Unknown value"
    return clean, errors


def validate_listing(db, form: Mapping) -> dict:
    """Compatibility helper: return only the field errors for a listing."""

    return prepare_listing(db, form)[1]
