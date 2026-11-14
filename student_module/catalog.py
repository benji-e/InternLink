"""Departments and programmes that a university coordinator manages.

Students pick their university, department and programme from this catalog at
sign-up, so a university can only take student registrations once it has at
least one department with a programme.
"""

from __future__ import annotations

import re

from psycopg.rows import dict_row

from .service import StudentError

# programme_group drives matching: programmes in the same group count as related.
PROGRAMME_GROUPS = (
    "agriculture", "arts", "business", "computing", "education",
    "engineering", "health", "law", "science", "social_sciences",
)
_GROUP_RE = re.compile(r"^[a-z][a-z_]{1,39}$")


def _name(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StudentError(422, "INVALID_INPUT", f"{label} is required.")
    cleaned = " ".join(value.split())
    if len(cleaned) > 160:
        raise StudentError(422, "INVALID_INPUT", f"{label} must be at most 160 characters.")
    return cleaned


def _group(value) -> str:
    group = value.strip().lower().replace(" ", "_") if isinstance(value, str) else ""
    if not _GROUP_RE.fullmatch(group):
        raise StudentError(422, "INVALID_INPUT", "Choose a programme group.")
    return group


def list_catalog(conn, university_id: int, department_id: int | None) -> dict:
    """Departments (with their programmes) visible to a coordinator."""
    with conn.cursor(row_factory=dict_row) as cur:
        departments = cur.execute(
            """
            SELECT department_id AS id, name FROM departments
            WHERE university_id = %s AND (%s::bigint IS NULL OR department_id = %s)
            ORDER BY name
            """,
            (university_id, department_id, department_id),
        ).fetchall()
        programmes = cur.execute(
            """
            SELECT p.programme_id AS id, p.department_id, p.name, p.programme_group
            FROM programmes p JOIN departments d ON d.department_id = p.department_id
            WHERE d.university_id = %s AND (%s::bigint IS NULL OR d.department_id = %s)
            ORDER BY p.name
            """,
            (university_id, department_id, department_id),
        ).fetchall()
    by_department: dict[int, list[dict]] = {}
    for programme in programmes:
        by_department.setdefault(programme.pop("department_id"), []).append(programme)
    for department in departments:
        department["programmes"] = by_department.get(department["id"], [])
    return {
        "departments": departments,
        "programme_groups": list(PROGRAMME_GROUPS),
        # A coordinator scoped to one department manages only that department's programmes.
        "can_add_departments": department_id is None,
    }


def add_department(conn, university_id: int, scope_department_id: int | None, payload: dict) -> dict:
    if scope_department_id is not None:
        raise StudentError(403, "UNIVERSITY_COORDINATOR_REQUIRED", "Only a university-wide coordinator can add departments.")
    name = _name(payload.get("name"), "Department name")
    with conn.cursor(row_factory=dict_row) as cur:
        if cur.execute(
            "SELECT 1 FROM departments WHERE university_id = %s AND lower(name) = lower(%s)",
            (university_id, name),
        ).fetchone():
            raise StudentError(409, "ALREADY_EXISTS", f"{name} already exists.")
        row = cur.execute(
            "INSERT INTO departments (university_id, name) VALUES (%s, %s) RETURNING department_id AS id, name",
            (university_id, name),
        ).fetchone()
    return {"department": {**row, "programmes": []}}


def add_programme(conn, university_id: int, scope_department_id: int | None, payload: dict) -> dict:
    try:
        department_id = int(payload.get("department_id"))
    except (TypeError, ValueError):
        raise StudentError(422, "INVALID_INPUT", "Choose a department.") from None
    if scope_department_id is not None and department_id != scope_department_id:
        raise StudentError(403, "OUT_OF_SCOPE", "You can only add programmes to your own department.")
    name = _name(payload.get("name"), "Programme name")
    group = _group(payload.get("programme_group"))
    with conn.cursor(row_factory=dict_row) as cur:
        if not cur.execute(
            "SELECT 1 FROM departments WHERE department_id = %s AND university_id = %s",
            (department_id, university_id),
        ).fetchone():
            raise StudentError(404, "DEPARTMENT_NOT_FOUND", "Department not found at your university.")
        if cur.execute(
            "SELECT 1 FROM programmes WHERE department_id = %s AND lower(name) = lower(%s)",
            (department_id, name),
        ).fetchone():
            raise StudentError(409, "ALREADY_EXISTS", f"{name} already exists in this department.")
        row = cur.execute(
            """
            INSERT INTO programmes (department_id, name, programme_group) VALUES (%s, %s, %s)
            RETURNING programme_id AS id, name, programme_group
            """,
            (department_id, name, group),
        ).fetchone()
    return {"programme": row}
