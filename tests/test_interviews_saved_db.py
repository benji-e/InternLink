"""Interview stage (09), saved internships and admin request screens on PostgreSQL.

Integration tests. They need PostgreSQL 16 with 01-03, 05, 08 and 09 loaded,
and INTERNLINK_TEST_DSN set. Skipped otherwise. Each test is rolled back.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

from student_module import admin, messages, public, saved
from student_module.service import StudentError, list_applications

DSN = os.environ.get("INTERNLINK_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="INTERNLINK_TEST_DSN not set (no test database)")


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


def shortlisted(conn):
    """Shortlist one application under review (inside the test transaction)."""
    return conn.execute(
        """
        UPDATE applications a SET status = 'shortlisted'
        FROM student_profiles sp
        WHERE sp.student_id = a.student_id
          AND a.application_id = (SELECT min(application_id) FROM applications WHERE status = 'under_review')
        RETURNING a.application_id, a.student_id, sp.user_id
        """
    ).fetchone()


class _SharedPool:
    """Hands the employer adapter the test's own connection, so its writes roll back too."""

    class _Connection:
        def __init__(self, conn):
            object.__setattr__(self, "_conn", conn)

        def __getattr__(self, name):
            return getattr(self._conn, name)

        def __setattr__(self, name, value):
            if name != "autocommit":  # keep the test transaction open
                setattr(self._conn, name, value)

    def __init__(self, conn):
        self._wrapped = self._Connection(conn)

    def getconn(self, timeout=None):
        return self._wrapped

    def putconn(self, conn):
        pass


def test_interview_stage_rules(conn):
    row = shortlisted(conn)
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute("UPDATE applications SET status = 'interview' WHERE application_id = %s", (row["application_id"],))
    when = datetime.now(timezone.utc) + timedelta(days=2)
    conn.execute(
        "UPDATE applications SET status = 'interview', interview_at = %s, interview_note = 'Kampala office' WHERE application_id = %s",
        (when, row["application_id"]),
    )
    note = conn.execute(
        "SELECT message FROM notifications WHERE related_id = %s AND related_type = 'applications' ORDER BY notification_id DESC LIMIT 1",
        (row["application_id"],),
    ).fetchone()["message"]
    assert "interview stage" in note
    application = next(item for item in list_applications(conn, row["student_id"]) if item["application_id"] == row["application_id"])
    assert application["interview_note"] == "Kampala office"
    # Messaging is open at the interview stage.
    employer = conn.execute(
        "SELECT u.user_id FROM users u JOIN listings l ON l.company_id = u.company_id JOIN applications a ON a.listing_id = l.listing_id "
        "WHERE a.application_id = %s AND u.role = 'employer' LIMIT 1",
        (row["application_id"],),
    ).fetchone()["user_id"]
    conn.execute(
        "INSERT INTO messages (application_id, sender_id, recipient_id, body) VALUES (%s, %s, %s, 'See you')",
        (row["application_id"], employer, row["user_id"]),
    )
    assert messages.thread(conn, row["user_id"], row["student_id"], row["application_id"])["can_reply"]
    # Interview can't go back to shortlisted.
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        with conn.transaction():
            conn.execute("UPDATE applications SET status = 'shortlisted' WHERE application_id = %s", (row["application_id"],))
    conn.execute("UPDATE applications SET status = 'accepted' WHERE application_id = %s", (row["application_id"],))
    assert conn.execute("SELECT 1 FROM placements WHERE application_id = %s", (row["application_id"],)).fetchone()


def test_employer_module_interview_on_postgres(conn):
    """The employer service's decide action works against the real schema and triggers."""
    from employer_module.internlink_employer.db import PostgresDatabase
    from employer_module.internlink_employer.services import decide_application, list_applicants, view_applicant
    from employer_module.internlink_employer.session import Session

    shortlisted_id = shortlisted(conn)["application_id"]
    row = conn.execute(
        """
        SELECT a.application_id, l.listing_id, l.company_id, u.user_id FROM applications a
        JOIN listings l ON l.listing_id = a.listing_id JOIN users u ON u.company_id = l.company_id AND u.role = 'employer'
        WHERE a.application_id = %s LIMIT 1
        """,
        (shortlisted_id,),
    ).fetchone()
    db = PostgresDatabase(_SharedPool(conn))
    session = Session(user_id=row["user_id"], role="employer", status="active", company_id=row["company_id"])
    when = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    assert decide_application(db, session, row["application_id"], "interview", interview_at=when)["status"] == "interview"
    board = list_applicants(db, session, row["listing_id"])
    moved = next(item for item in board["applicants"] if item["application_id"] == row["application_id"])
    assert moved["status"] == "interview" and moved["interview_at"] is not None
    assert isinstance(moved["student_verified"], bool)
    detail = view_applicant(db, session, row["application_id"])
    assert detail["can_message"] and detail["listing_skills"]
    assert decide_application(db, session, row["application_id"], "reject", reason="Position filled")["status"] == "rejected"
    assert db.query_one("SELECT decision_note FROM applications WHERE application_id = %s", [row["application_id"]])["decision_note"] == "Position filled"


def test_saved_internships(conn):
    row = shortlisted(conn)
    listing_id = public.home(conn)["latest"][0]["listing_id"]
    assert saved.save(conn, row["student_id"], listing_id)["saved"]
    saved.save(conn, row["student_id"], listing_id)  # saving twice is fine
    items = saved.list_saved(conn, row["student_id"])
    assert [item["listing_id"] for item in items] == [listing_id] and items[0]["is_open"]
    assert public.opportunity_detail(conn, listing_id, row["student_id"])["saved"] is True
    result = public.search_opportunities(conn, {"page_size": "50"}, row["student_id"])
    assert next(item for item in result["results"] if item["listing_id"] == listing_id)["saved"] is True
    saved.unsave(conn, row["student_id"], listing_id)
    assert saved.list_saved(conn, row["student_id"]) == []
    with pytest.raises(StudentError) as error:
        saved.save(conn, row["student_id"], 999_999)
    assert error.value.status == 404


def test_admin_registration_detail_and_university_requests(conn):
    company = conn.execute("SELECT company_id FROM companies WHERE verification_status = 'pending' LIMIT 1").fetchone()
    detail = admin.registration_detail(conn, "company", company["company_id"])
    assert detail["org_type"] == "company" and "draft_listings" in detail and "people" in detail
    university = conn.execute("SELECT university_id FROM universities WHERE status = 'pending' LIMIT 1").fetchone()
    assert admin.registration_detail(conn, "university", university["university_id"])["email_domain"]
    with pytest.raises(StudentError):
        admin.registration_detail(conn, "planet", 1)

    public.request_university(conn, {"university_name": "Lira University", "requester_email": "a@x.com", "coordinator_email": "c@lirauni.ac.ug"})
    public.request_university(conn, {"university_name": "lira university", "requester_email": "b@x.com"})
    requests = admin.university_requests(conn)
    lira = next(item for item in requests if item["university_name"].lower() == "lira university")
    assert lira["requests"] == 2 and lira["coordinator_emails"] == ["c@lirauni.ac.ug"]
    assert admin.close_university_request(conn, {"university_name": "Lira University", "status": "added"})["updated"] == 2
    assert all(item["university_name"].lower() != "lira university" for item in admin.university_requests(conn))
    with pytest.raises(StudentError):
        admin.close_university_request(conn, {"university_name": "Lira University", "status": "maybe"})


def test_coordinator_can_approve_a_placement_over_http(conn):
    """Regression: approving always failed because confirmed placements need dates.

    This goes through the real handler, so its change is committed. It skips once
    the seed data has no pending placement left.
    """
    import json
    import threading
    from http.server import ThreadingHTTPServer
    from unittest.mock import patch
    from urllib.request import Request, urlopen

    import jwt

    import api.index as api_module

    pending = conn.execute(
        """
        SELECT p.placement_id, l.duration_weeks, u.user_id AS coordinator_id
        FROM placements p JOIN applications a ON a.application_id = p.application_id
        JOIN listings l ON l.listing_id = a.listing_id
        JOIN student_profiles sp ON sp.student_id = a.student_id
        JOIN users u ON u.role = 'coordinator' AND u.status = 'active' AND u.university_id = sp.university_id
             AND (u.department_id IS NULL OR u.department_id = sp.department_id)
        WHERE p.status = 'pending' LIMIT 1
        """
    ).fetchone()
    if pending is None:
        pytest.skip("no pending placement left in the test database")
    conn.rollback()
    secret = "test-signing-secret-that-is-at-least-32-characters"
    with patch.dict(os.environ, {"INTERNLINK_DSN": DSN, "INTERNLINK_JWT_SECRET": secret}):
        server = ThreadingHTTPServer(("127.0.0.1", 0), api_module.handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            token = jwt.encode({"sub": str(pending["coordinator_id"]), "role": "coordinator",
                                "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}, secret, algorithm="HS256")
            request = Request(
                f"http://127.0.0.1:{server.server_port}/api/v1/coordinator/placements/{pending['placement_id']}",
                data=json.dumps({"action": "confirmed", "start_date": "2027-01-11"}).encode(),
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST",
            )
            with urlopen(request, timeout=10) as response:
                assert response.status == 200
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
    row = conn.execute("SELECT status, start_date, end_date FROM placements WHERE placement_id = %s", (pending["placement_id"],)).fetchone()
    assert row["status"] == "confirmed"
    assert str(row["start_date"]) == "2027-01-11"
    assert (row["end_date"] - row["start_date"]).days == pending["duration_weeks"] * 7
