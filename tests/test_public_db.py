"""Public pages (home, search, detail), university requests and student replies.

Integration tests. They need PostgreSQL 16 with 01_schema, 02_functions_triggers,
03_views_functions, 05_seed and 08_university_requests loaded, and
INTERNLINK_TEST_DSN set. Skipped otherwise. Each test is rolled back.
"""
import os

import pytest

from student_module import messages, public
from student_module.service import StudentError

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


def student(conn):
    """The seeded student with an accepted application and an employer message."""
    row = conn.execute(
        """
        SELECT a.application_id, a.student_id, sp.user_id FROM applications a
        JOIN student_profiles sp ON sp.student_id = a.student_id
        WHERE a.status = 'accepted' AND EXISTS (SELECT 1 FROM messages m WHERE m.application_id = a.application_id)
        LIMIT 1
        """
    ).fetchone()
    assert row, "seed data should include an accepted application with messages"
    return row


def test_home_lists_latest_open_internships_and_partner_universities(conn):
    result = public.home(conn)
    assert 0 < len(result["latest"]) <= 4
    assert "Mbarara University of Science and Technology" in result["universities"]
    assert "Kampala International University" not in result["universities"]  # still pending


def test_search_filters_and_sector_counts(conn):
    everything = public.search_opportunities(conn, {})
    assert everything["count"] == sum(item["count"] for item in everything["sectors"])
    sector = everything["sectors"][0]["name"]
    only = public.search_opportunities(conn, {"sector": sector})
    assert only["count"] == everything["sectors"][0]["count"]
    # Sector counts stay the same when a sector is picked, so others remain choosable.
    assert only["sectors"] == everything["sectors"]
    remote = public.search_opportunities(conn, {"remote": "true"})
    assert all(row["is_remote"] for row in remote["results"])
    page = public.search_opportunities(conn, {"page_size": "1", "page": "2", "sort": "newest"})
    assert len(page["results"]) == 1


@pytest.mark.parametrize("filters", [{"sort": "random"}, {"remote": "maybe"}, {"min_weeks": "99"}, {"page": "0"}])
def test_search_rejects_bad_filters(conn, filters):
    with pytest.raises(StudentError) as error:
        public.search_opportunities(conn, filters)
    assert error.value.status == 422


def test_detail_shows_match_only_to_students(conn):
    listing_id = public.home(conn)["latest"][0]["listing_id"]
    anonymous = public.opportunity_detail(conn, listing_id)
    assert anonymous["match"] is None and anonymous["application"] is None
    sid = student(conn)["student_id"]
    signed_in = public.opportunity_detail(conn, listing_id, sid)
    assert 0 <= signed_in["match"]["score"] <= 100
    assert set(signed_in["match"]["breakdown"]) == {"skills", "programme", "interests", "location"}
    with pytest.raises(StudentError) as error:
        public.opportunity_detail(conn, 999_999)
    assert error.value.status == 404


def test_university_programmes_include_department(conn):
    programmes = public.university_programmes(conn, 1)
    assert programmes and all(item["department_id"] and item["department"] for item in programmes)
    assert public.university_programmes(conn, 3) == []  # pending university


def test_university_request_is_saved_once_per_person(conn):
    payload = {"university_name": "Lira University", "requester_email": "Pupil@Example.com"}
    public.request_university(conn, payload)
    public.request_university(conn, {**payload, "university_name": "lira   university"})
    count = conn.execute("SELECT count(*) AS n FROM university_requests WHERE requester_email = 'pupil@example.com'").fetchone()["n"]
    assert count == 1
    with pytest.raises(StudentError) as error:
        public.request_university(conn, {"university_name": "Makerere University", "requester_email": "a@b.co"})
    assert error.value.status == 409
    with pytest.raises(StudentError):
        public.request_university(conn, {"university_name": "X", "requester_email": ""})


def test_student_can_read_and_reply_to_employer_thread(conn):
    row = student(conn)
    before = messages.unread_by_application(conn, row["user_id"])
    thread = messages.thread(conn, row["user_id"], row["student_id"], row["application_id"])
    assert thread["can_reply"] and thread["employer_name"]
    assert messages.unread_by_application(conn, row["user_id"]).get(row["application_id"], 0) == 0
    assert before is not None
    sent = messages.reply(conn, row["user_id"], row["student_id"], row["application_id"], {"body": "  Thank you!  "})
    assert sent["message"]["body"] == "Thank you!"
    with pytest.raises(StudentError):
        messages.reply(conn, row["user_id"], row["student_id"], row["application_id"], {"body": "   "})


def test_student_cannot_message_without_employer_thread_or_for_others(conn):
    row = student(conn)
    other = conn.execute(
        "SELECT application_id FROM applications WHERE student_id <> %s LIMIT 1", (row["student_id"],)
    ).fetchone()
    with pytest.raises(StudentError) as error:
        messages.thread(conn, row["user_id"], row["student_id"], other["application_id"])
    assert error.value.status == 404
    conn.execute("DELETE FROM messages WHERE application_id = %s", (row["application_id"],))
    with pytest.raises(StudentError) as error:
        messages.reply(conn, row["user_id"], row["student_id"], row["application_id"], {"body": "Hello"})
    assert error.value.code == "CONVERSATION_NOT_STARTED"
