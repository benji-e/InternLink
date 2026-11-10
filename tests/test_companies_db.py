"""Company directory, company pages, logos and suggestions (11_companies_logos.sql).

Integration tests. They need PostgreSQL 16 with 01-03, 05 and 08-11 loaded,
and INTERNLINK_TEST_DSN set. Skipped otherwise. Each test is rolled back.
"""
import os

import pytest

from student_module import companies, public, saved
from student_module.service import StudentError

DSN = os.environ.get("INTERNLINK_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="INTERNLINK_TEST_DSN not set (no test database)")

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 64


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


def verified_company(conn):
    return conn.execute(
        "SELECT company_id, name FROM companies WHERE verification_status = 'verified' ORDER BY company_id LIMIT 1"
    ).fetchone()


def test_directory_lists_verified_companies_even_without_open_internships(conn):
    result = companies.list_companies(conn, {})
    names = {row["name"] for row in result["companies"]}
    pending = conn.execute("SELECT name FROM companies WHERE verification_status = 'pending'").fetchall()
    assert names and not names & {row["name"] for row in pending}
    # A verified company whose internships are all closed still appears.
    company = verified_company(conn)
    conn.execute("UPDATE listings SET status = 'closed' WHERE company_id = %s AND status = 'open'", (company["company_id"],))
    found = companies.list_companies(conn, {"q": company["name"][:5]})
    row = next(item for item in found["companies"] if item["company_id"] == company["company_id"])
    assert row["open_internships"] == 0
    assert result["sectors"]


def test_company_page(conn):
    company = verified_company(conn)
    page = companies.company_profile(conn, company["company_id"])
    assert page["name"] == company["name"] and isinstance(page["open_internships"], list)
    assert page["past_internships"] >= 0 and page["interns_placed"] >= 0
    pending = conn.execute("SELECT company_id FROM companies WHERE verification_status = 'pending' LIMIT 1").fetchone()
    with pytest.raises(StudentError) as error:
        companies.company_profile(conn, pending["company_id"])
    assert error.value.status == 404


def test_logo_upload_replace_and_public_visibility(conn):
    company = verified_company(conn)
    companies.save_logo(conn, company["company_id"], PNG)
    assert bytes(companies.read_logo(conn, company["company_id"])["data"]) == PNG
    companies.save_logo(conn, company["company_id"], JPEG)
    assert companies.read_logo(conn, company["company_id"])["content_type"] == "image/jpeg"
    # Listings, saved items and the directory say the company has a logo.
    listing = conn.execute("SELECT listing_id FROM v_open_listings WHERE company_id = %s LIMIT 1", (company["company_id"],)).fetchone()
    if listing:
        detail = public.opportunity_detail(conn, listing["listing_id"])
        assert detail["has_logo"] and detail["company_id"] == company["company_id"]
        results = public.search_opportunities(conn, {"page_size": "50"})["results"]
        assert next(item for item in results if item["listing_id"] == listing["listing_id"])["has_logo"]
        student = conn.execute("SELECT student_id FROM student_profiles LIMIT 1").fetchone()["student_id"]
        saved.save(conn, student, listing["listing_id"])
        assert next(item for item in saved.list_saved(conn, student) if item["listing_id"] == listing["listing_id"])["has_logo"]
    companies.delete_logo(conn, company["company_id"])
    with pytest.raises(StudentError):
        companies.read_logo(conn, company["company_id"])


def test_pending_company_logo_is_private(conn):
    pending = conn.execute("SELECT company_id FROM companies WHERE verification_status = 'pending' LIMIT 1").fetchone()
    companies.save_logo(conn, pending["company_id"], WEBP)
    assert companies.read_own_logo(conn, pending["company_id"])["content_type"] == "image/webp"
    with pytest.raises(StudentError):
        companies.read_logo(conn, pending["company_id"])


@pytest.mark.parametrize("data,status", [
    (b"", 422),
    (b"<svg onload=alert(1)></svg>", 415),
    (b"GIF89a....", 415),
    (b"\x89PNG\r\n\x1a\n" + b"0" * companies.MAX_LOGO_BYTES, 413),
], ids=["empty", "svg", "gif", "too-large"])
def test_bad_logos_are_refused(conn, data, status):
    with pytest.raises(StudentError) as error:
        companies.save_logo(conn, verified_company(conn)["company_id"], data)
    assert error.value.status == status


def test_suggest_a_company(conn):
    companies.request_company(conn, {"company_name": "MTN Uganda", "website": "https://mtn.co.ug", "requester_email": "a@x.com"})
    companies.request_company(conn, {"company_name": "mtn  uganda", "requester_email": "a@x.com"})  # same person: once
    companies.request_company(conn, {"company_name": "MTN Uganda", "requester_email": "b@x.com"})
    mtn = next(item for item in companies.company_requests(conn) if item["company_name"].lower() == "mtn uganda")
    assert mtn["requests"] == 2 and mtn["websites"] == ["https://mtn.co.ug"]
    with pytest.raises(StudentError) as error:
        companies.request_company(conn, {"company_name": verified_company(conn)["name"], "requester_email": "c@x.com"})
    assert error.value.status == 409
    with pytest.raises(StudentError):
        companies.request_company(conn, {"company_name": "Airtel", "requester_email": "not-an-email"})
    assert companies.close_company_request(conn, {"company_name": "MTN Uganda", "status": "invited"})["updated"] == 2
    assert all(item["company_name"].lower() != "mtn uganda" for item in companies.company_requests(conn))
