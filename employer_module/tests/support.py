"""Shared test fixtures for the Employer module."""

from __future__ import annotations

import io
import json
import secrets
from dataclasses import dataclass, field
from datetime import date, timedelta
from types import SimpleNamespace
from wsgiref.util import setup_testing_defaults

from internlink_employer.adapters import (
    MemoryMailer,
    MemoryMatchingCache,
    MemoryNotifier,
    MemoryStorage,
)
from internlink_employer.api import EmployerAPI
from internlink_employer.context import AppContext
from internlink_employer.db import SQLiteDatabase
from internlink_employer.security import ReferenceTokenService
from internlink_employer.session import open_session
from internlink_employer.services.common import recount_slots

SECRET = "unit-test-secret-that-is-at-least-32-bytes-long"


def make_context(storage_files: dict[str, bytes] | None = None) -> SimpleNamespace:
    db = SQLiteDatabase(":memory:")
    auth = ReferenceTokenService(SECRET)
    mailer = MemoryMailer()
    notifier = MemoryNotifier()
    storage = MemoryStorage(storage_files or {})
    cache = MemoryMatchingCache()
    ctx = AppContext(
        db=db,
        auth=auth,
        mailer=mailer,
        notifier=notifier,
        storage=storage,
        cache=cache,
        base_url="https://internlink.test",
    )
    return SimpleNamespace(
        db=db,
        auth=auth,
        mailer=mailer,
        notifier=notifier,
        storage=storage,
        cache=cache,
        ctx=ctx,
        api=EmployerAPI(ctx),
    )


def seed_reference(db) -> dict:
    skill_python = db.insert("skills", {"name": "Python"})
    skill_sql = db.insert("skills", {"name": "SQL"})
    skill_writing = db.insert("skills", {"name": "Writing"})
    programme = db.insert("programmes", {"name": "Bachelor of IT"})
    programme2 = db.insert("programmes", {"name": "BSc Computer Science"})
    interest = db.insert("interests", {"name": "Fintech"})
    interest2 = db.insert("interests", {"name": "Agritech"})
    university = db.insert("universities", {"name": "Makerere University"})
    return {
        "skill_python": skill_python,
        "skill_sql": skill_sql,
        "skill_writing": skill_writing,
        "programme": programme,
        "programme2": programme2,
        "interest": interest,
        "interest2": interest2,
        "university": university,
    }


def add_company(
    db,
    name: str | None = None,
    *,
    verification_status: str = "verified",
    rejection_reason: str | None = None,
) -> int:
    suffix = secrets.token_hex(3)
    name = name or f"Company {suffix}"
    return db.insert_returning_id(
        "companies",
        {
            "name": name,
            "sector": "Technology",
            "location": "Kampala",
            "description": "A test company",
            "contact_email": f"info-{suffix}@example.com",
            "website": "https://example.com",
            "verification_status": verification_status,
            "rejection_reason": rejection_reason,
        },
    )


def add_employer(
    db,
    company_id: int,
    email: str | None = None,
    *,
    status: str = "active",
    full_name: str = "Employer Rep",
) -> int:
    suffix = secrets.token_hex(3)
    return db.insert_returning_id(
        "users",
        {
            "email": email or f"employer-{suffix}@example.com",
            "password_hash": "not-used-in-token-tests",
            "full_name": full_name,
            "phone": "+256700000000",
            "role": "employer",
            "status": status,
            "company_id": company_id,
        },
    )


def add_employer_account(db, **kwargs) -> tuple[int, int]:
    company_id = add_company(
        db,
        kwargs.pop("name", None),
        verification_status=kwargs.pop("verification_status", "verified"),
        rejection_reason=kwargs.pop("rejection_reason", None),
    )
    user_id = add_employer(db, company_id, kwargs.pop("email", None), **kwargs)
    return company_id, user_id


def add_student(
    db,
    refs: dict,
    *,
    email: str | None = None,
    full_name: str = "Student One",
    year: int = 2,
    cv_path: str | None = None,
    skills: list[int] | None = None,
    interests: list[int] | None = None,
    relocation: bool = False,
) -> int:
    suffix = secrets.token_hex(3)
    user_id = db.insert_returning_id(
        "users",
        {
            "email": email or f"student-{suffix}@example.com",
            "password_hash": "not-used-in-token-tests",
            "full_name": full_name,
            "role": "student",
            "status": "active",
        },
    )
    student_id = db.insert_returning_id(
        "student_profiles",
        {
            "user_id": user_id,
            "programme_id": refs["programme"],
            "university_id": refs["university"],
            "year_of_study": year,
            "preferred_location": "Kampala",
            "willing_to_relocate": relocation,
            "cv_path": cv_path,
        },
    )
    for skill_id in skills or [refs["skill_python"]]:
        db.insert("student_skills", {"student_id": student_id, "skill_id": skill_id})
    for interest_id in interests or [refs["interest"]]:
        db.insert(
            "student_interests", {"student_id": student_id, "interest_id": interest_id}
        )
    return student_id


def student_user_id(db, student_id: int) -> int:
    return int(
        db.query_one(
            "SELECT user_id FROM student_profiles WHERE student_id = %s", [student_id]
        )["user_id"]
    )


def add_listing(
    db,
    company_id: int,
    posted_by: int,
    refs: dict,
    *,
    title: str = "Software Engineering Intern",
    description: str = "Build useful software with the team.",
    status: str = "open",
    slots: int = 2,
    duration_weeks: int = 12,
    deadline: date | None = None,
    required_skills: list[int] | None = None,
    optional_skills: list[int] | None = None,
    programmes: list[int] | None = None,
    interests: list[int] | None = None,
) -> int:
    deadline = deadline or (date.today() + timedelta(days=30))
    listing_id = db.insert_returning_id(
        "listings",
        {
            "company_id": company_id,
            "posted_by": posted_by,
            "title": title,
            "description": description,
            "sector": "Technology",
            "location": "Kampala",
            "is_remote": False,
            "duration_weeks": duration_weeks,
            "slots": slots,
            "application_deadline": deadline.isoformat(),
            "status": status,
            "posted_at": "2026-01-01 00:00:00" if status == "open" else None,
            "closed_at": "2026-01-02 00:00:00" if status == "closed" else None,
        },
    )
    for skill_id in required_skills if required_skills is not None else [refs["skill_python"]]:
        db.insert(
            "listing_skills",
            {"listing_id": listing_id, "skill_id": skill_id, "is_required": True},
        )
    for skill_id in optional_skills or []:
        db.insert(
            "listing_skills",
            {"listing_id": listing_id, "skill_id": skill_id, "is_required": False},
        )
    for programme_id in programmes if programmes is not None else [refs["programme"]]:
        db.insert(
            "listing_programmes",
            {"listing_id": listing_id, "programme_id": programme_id},
        )
    for interest_id in interests if interests is not None else [refs["interest"]]:
        db.insert(
            "listing_interests",
            {"listing_id": listing_id, "interest_id": interest_id},
        )
    return listing_id


def add_application(
    db,
    listing_id: int,
    student_id: int,
    *,
    status: str = "submitted",
    match_score: float = 75.0,
    cover_note: str = "I would love to join.",
) -> int:
    return db.insert_returning_id(
        "applications",
        {
            "listing_id": listing_id,
            "student_id": student_id,
            "cover_note": cover_note,
            "match_score": match_score,
            "status": status,
        },
    )


def add_placement(
    db,
    application_id: int,
    *,
    status: str = "confirmed",
    start_date: date | None = None,
    end_date: date | None = None,
    completion_note: str | None = None,
) -> int:
    start_date = start_date or (date.today() - timedelta(days=60))
    end_date = end_date or (date.today() - timedelta(days=1))
    placement_id = db.insert_returning_id(
        "placements",
        {
            "application_id": application_id,
            "status": status,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "completion_note": completion_note,
        },
    )
    listing_id = db.query_one(
        "SELECT listing_id FROM applications WHERE application_id = %s", [application_id]
    )["listing_id"]
    recount_slots(db, listing_id)
    return placement_id


def session_for(harness, user_id: int):
    token = harness.auth.issue_token(user_id)
    session = open_session(harness.db, harness.auth, token)
    return session, token


@dataclass
class ApiResponse:
    status: int
    headers: dict = field(default_factory=dict)
    body: bytes = b""

    @property
    def json(self):
        return json.loads(self.body.decode("utf-8"))

    @property
    def content_type(self):
        return self.headers.get("Content-Type", "")


def call_api(
    app,
    path: str,
    payload=None,
    *,
    token: str | None = None,
    method: str = "POST",
    raw_body: bytes | str | None = None,
    content_length: str | None = None,
) -> ApiResponse:
    if raw_body is not None:
        body = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body
    elif payload is not None:
        body = json.dumps(payload).encode("utf-8")
    else:
        body = b""

    environ: dict = {}
    setup_testing_defaults(environ)
    environ.update(
        {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "CONTENT_LENGTH": content_length if content_length is not None else str(len(body)),
            "wsgi.input": io.BytesIO(body),
            "CONTENT_TYPE": "application/json",
        }
    )
    if token:
        environ["HTTP_AUTHORIZATION"] = f"Bearer {token}"

    captured: dict = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = dict(headers)
        return None

    chunks = app(environ, start_response)
    response_body = b"".join(chunks)
    return ApiResponse(
        status=int(captured["status"].split()[0]),
        headers=captured.get("headers", {}),
        body=response_body,
    )
