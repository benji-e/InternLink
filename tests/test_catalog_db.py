"""Coordinator-managed departments and programmes, and the catalog seed script.

Integration tests. They need PostgreSQL 16 with 01_schema, 02_functions_triggers,
03_views_functions and 05_seed loaded, and INTERNLINK_TEST_DSN set. Skipped
otherwise. Every test runs in a transaction that is rolled back.
"""
import importlib.util
import os
from pathlib import Path

import pytest

from student_module import catalog
from student_module.service import StudentError, list_departments, list_programmes, list_universities

DSN = os.environ.get("INTERNLINK_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="INTERNLINK_TEST_DSN not set (no test database)")

MUST = 1  # seeded university with departments


@pytest.fixture
def conn():
    import psycopg
    from psycopg.rows import dict_row

    connection = psycopg.connect(DSN, row_factory=dict_row)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def new_university(conn, name="Lira University", domain="lirauni.ac.ug"):
    return conn.execute(
        "INSERT INTO universities (name, location, email_domain, status, verified_at) "
        "VALUES (%s, 'Lira', %s, 'verified', now()) RETURNING university_id",
        (name, domain),
    ).fetchone()["university_id"]


def test_new_university_starts_empty_and_can_add_department_and_programme(conn):
    university_id = new_university(conn)
    assert catalog.list_catalog(conn, university_id, None)["departments"] == []

    department = catalog.add_department(conn, university_id, None, {"name": "  Computer   Science "})["department"]
    assert department["name"] == "Computer Science"
    programme = catalog.add_programme(conn, university_id, None, {
        "department_id": department["id"], "name": "BSc Computer Science", "programme_group": "computing",
    })["programme"]
    assert programme["programme_group"] == "computing"

    # The public sign-up lists now show the new options.
    assert any(item["id"] == university_id and item["email_domain"] == "lirauni.ac.ug" for item in list_universities(conn))
    assert list_departments(conn, university_id) == [{"id": department["id"], "name": "Computer Science"}]
    assert list_programmes(conn, department["id"]) == [{"id": programme["id"], "name": "BSc Computer Science"}]

    result = catalog.list_catalog(conn, university_id, None)
    assert result["can_add_departments"] is True
    assert result["departments"][0]["programmes"] == [programme]


def test_duplicate_names_are_rejected_case_insensitively(conn):
    with pytest.raises(StudentError) as error:
        catalog.add_department(conn, MUST, None, {"name": "software engineering"})
    assert error.value.status == 409
    department_id = list_departments(conn, MUST)[0]["id"]
    existing = list_programmes(conn, department_id)[0]["name"]
    with pytest.raises(StudentError) as error:
        catalog.add_programme(conn, MUST, None, {
            "department_id": department_id, "name": existing.upper(), "programme_group": "computing",
        })
    assert error.value.status == 409


def test_department_scoped_coordinator_is_limited_to_own_department(conn):
    departments = list_departments(conn, MUST)
    own, other = departments[0]["id"], departments[1]["id"]
    result = catalog.list_catalog(conn, MUST, own)
    assert result["can_add_departments"] is False
    assert [item["id"] for item in result["departments"]] == [own]
    with pytest.raises(StudentError) as error:
        catalog.add_department(conn, MUST, own, {"name": "Statistics"})
    assert error.value.status == 403
    with pytest.raises(StudentError) as error:
        catalog.add_programme(conn, MUST, own, {"department_id": other, "name": "X", "programme_group": "science"})
    assert error.value.status == 403
    added = catalog.add_programme(conn, MUST, own, {"department_id": own, "name": "Diploma in Computing", "programme_group": "computing"})
    assert added["programme"]["name"] == "Diploma in Computing"


def test_cannot_add_programme_to_another_universitys_department(conn):
    other_university = new_university(conn)
    must_department = list_departments(conn, MUST)[0]["id"]
    with pytest.raises(StudentError) as error:
        catalog.add_programme(conn, other_university, None, {
            "department_id": must_department, "name": "BSc Hacking", "programme_group": "computing",
        })
    assert error.value.status == 404


@pytest.mark.parametrize("payload", [
    {"name": ""},
    {"name": "   "},
    {"name": "x" * 161},
    {"name": 42},
])
def test_department_name_validation(conn, payload):
    with pytest.raises(StudentError) as error:
        catalog.add_department(conn, MUST, None, payload)
    assert error.value.status == 422


@pytest.mark.parametrize("payload", [
    {"department_id": "abc", "name": "BSc X", "programme_group": "computing"},
    {"department_id": 1, "name": "BSc X", "programme_group": ""},
    {"department_id": 1, "name": "BSc X", "programme_group": "Bad-Group!"},
])
def test_programme_validation(conn, payload):
    with pytest.raises(StudentError) as error:
        catalog.add_programme(conn, MUST, None, payload)
    assert error.value.status == 422


def _load_seed_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "seed_catalog.py"
    spec = importlib.util.spec_from_file_location("seed_catalog", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_catalog_adds_missing_rows_and_is_idempotent(conn):
    seed = _load_seed_script()
    conn.execute("UPDATE universities SET status = 'pending', verified_at = NULL WHERE university_id = %s", (MUST,))
    first = seed.seed(conn)
    assert first["universities"] > 0 and first["departments"] > 0 and first["programmes"] > 0
    assert seed.seed(conn) == {"universities": 0, "departments": 0, "programmes": 0}
    # Existing universities keep their status.
    assert conn.execute("SELECT status FROM universities WHERE university_id = %s", (MUST,)).fetchone()["status"] == "pending"
    # Every seeded university that is verified can take student sign-ups.
    for university in list_universities(conn):
        departments = list_departments(conn, university["id"])
        assert departments, university["name"]
        assert all(list_programmes(conn, item["id"]) for item in departments), university["name"]


def test_seed_catalog_groups_are_known():
    seed = _load_seed_script()
    for _name, _location, domain, departments in seed.CATALOG:
        assert domain == domain.lower()
        for programmes in departments.values():
            assert programmes
            for _programme, group in programmes:
                assert group in catalog.PROGRAMME_GROUPS


def test_role_endpoints_read_rows_by_column_name():
    """Regression: pooled connections return tuples, which crashed every
    admin and coordinator endpoint. Read-only requests, so nothing is committed."""
    import json
    import threading
    from datetime import datetime, timedelta, timezone
    from http.server import ThreadingHTTPServer
    from unittest.mock import patch
    from urllib.request import Request, urlopen

    import jwt

    import api.index as api_module

    secret = "test-signing-secret-that-is-at-least-32-characters"
    with patch.dict(os.environ, {"INTERNLINK_DSN": DSN, "INTERNLINK_JWT_SECRET": secret}):
        server = ThreadingHTTPServer(("127.0.0.1", 0), api_module.handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def get(path, user_id, role):
                token = jwt.encode(
                    {"sub": str(user_id), "role": role, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
                    secret, algorithm="HS256",
                )
                request = Request(f"http://127.0.0.1:{server.server_port}{path}", headers={"Authorization": f"Bearer {token}"})
                with urlopen(request, timeout=10) as response:
                    return response.status, json.loads(response.read())

            # Seeded users: 1 = admin, 3 = MUST university-wide coordinator.
            status, body = get("/api/v1/coordinator/catalog", 3, "coordinator")
            assert status == 200 and body["can_add_departments"] is True
            assert {"Software Engineering", "Computer Science"} <= {item["name"] for item in body["departments"]}
            status, body = get("/api/v1/coordinator/students", 3, "coordinator")
            assert status == 200 and all(isinstance(row, dict) for row in body["students"])
            status, body = get("/api/v1/admin/users", 1, "admin")
            assert status == 200 and body["users"] and isinstance(body["users"][0], dict)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
