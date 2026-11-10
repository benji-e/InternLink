"""CV uploads, job alerts and coordinator invites (10_cv_alerts_invites.sql).

Integration tests. They need PostgreSQL 16 with 01-03, 05, 08, 09 and 10
loaded, and INTERNLINK_TEST_DSN set. Skipped otherwise. Each test is rolled back.
"""
import os

import pytest

from student_module import alerts, cv, invites
from student_module.service import StudentError, authenticate_user

DSN = os.environ.get("INTERNLINK_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="INTERNLINK_TEST_DSN not set (no test database)")

PDF = b"%PDF-1.4\n% test cv\n" + b"0" * 100
DOCX = b"PK\x03\x04" + b"\x00" * 26 + b"word/document.xml" + b"\x00" * 50


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


def a_student(conn):
    return conn.execute(
        "SELECT sp.student_id, sp.user_id FROM student_profiles sp JOIN users u ON u.user_id = sp.user_id "
        "WHERE u.status = 'active' ORDER BY sp.student_id LIMIT 1"
    ).fetchone()


# ---------- CVs ----------

def test_upload_replace_read_and_delete_cv(conn):
    student = a_student(conn)
    info = cv.save_cv(conn, student["student_id"], PDF, "../../My CV <final>.pdf")["cv"]
    assert info["filename"] == "My CV final.pdf" and info["content_type"] == cv.PDF and info["size_bytes"] == len(PDF)
    path = conn.execute("SELECT cv_path FROM student_profiles WHERE student_id = %s", (student["student_id"],)).fetchone()["cv_path"]
    assert path == f"db/{student['student_id']}.pdf"

    cv.save_cv(conn, student["student_id"], DOCX, "resume.docx")
    stored = cv.read_cv(conn, student["student_id"])
    assert stored["content_type"] == cv.DOCX and bytes(stored["data"]) == DOCX

    cv.delete_cv(conn, student["student_id"])
    assert cv.cv_info(conn, student["student_id"])["cv"] is None
    with pytest.raises(StudentError) as error:
        cv.read_cv(conn, student["student_id"])
    assert error.value.status == 404


@pytest.mark.parametrize("data,status", [
    (b"", 422),
    (b"GIF89a not a cv", 415),
    (b"PK\x03\x04 a zip without word", 415),
    (b"%PDF-" + b"0" * cv.MAX_CV_BYTES, 413),
], ids=["empty", "image", "other-zip", "too-large"])
def test_bad_cv_files_are_refused(conn, data, status):
    with pytest.raises(StudentError) as error:
        cv.save_cv(conn, a_student(conn)["student_id"], data, "x.pdf")
    assert error.value.status == status


def test_employer_storage_reads_database_cvs_and_falls_back(conn):
    student = a_student(conn)
    cv.save_cv(conn, student["student_id"], PDF, "cv.pdf")

    class Pool:  # hands the storage the test connection
        def connection(self):
            class Context:
                def __enter__(self_inner):
                    return conn

                def __exit__(self_inner, *exc):
                    return False
            return Context()

    class Disk:
        def read_bytes(self, path):
            return b"from disk:" + path.encode()

    storage = cv.DatabaseCvStorage(Pool(), fallback=Disk())
    assert storage.read_bytes(f"db/{student['student_id']}.pdf") == PDF
    assert storage.read_bytes("cvs/old.pdf") == b"from disk:cvs/old.pdf"
    with pytest.raises(FileNotFoundError):
        storage.read_bytes("db/999999.pdf")


# ---------- job alerts ----------

def test_create_list_and_delete_alerts(conn):
    student = a_student(conn)
    created = alerts.create_alert(conn, student["student_id"], {"q": "data", "remote": "true", "duration": "short", "page": "3"})
    assert created["created"] and created["alert"]["filters"] == {"q": "data", "remote": "true", "duration": "short"}
    assert created["alert"]["label"] == "“data”, remote, up to 8 weeks"
    again = alerts.create_alert(conn, student["student_id"], {"q": "data", "remote": "true", "duration": "short"})
    assert not again["created"] and again["alert"]["alert_id"] == created["alert"]["alert_id"]
    assert len(alerts.list_alerts(conn, student["student_id"])) == 1
    with pytest.raises(StudentError):
        alerts.create_alert(conn, student["student_id"], {"remote": "maybe"})
    alerts.delete_alert(conn, student["student_id"], created["alert"]["alert_id"])
    assert alerts.list_alerts(conn, student["student_id"]) == []
    with pytest.raises(StudentError):
        alerts.delete_alert(conn, student["student_id"], created["alert"]["alert_id"])


def test_alert_job_emails_only_new_matching_internships_once(conn):
    student = a_student(conn)
    alerts.create_alert(conn, student["student_id"], {})  # everything new
    # Pretend the alert was last checked a while ago, and one internship was posted since.
    conn.execute("UPDATE job_alerts SET last_checked_at = now() - interval '2 days' WHERE student_id = %s", (student["student_id"],))
    listing = conn.execute(
        "SELECT v.listing_id FROM v_open_listings v WHERE NOT EXISTS "
        "(SELECT 1 FROM applications a WHERE a.listing_id = v.listing_id AND a.student_id = %s) LIMIT 1",
        (student["student_id"],),
    ).fetchone()["listing_id"]
    conn.execute("UPDATE listings SET posted_at = now() - interval '1 day' WHERE listing_id = %s", (listing,))
    conn.execute("UPDATE listings SET posted_at = now() - interval '30 days' WHERE listing_id <> %s AND posted_at IS NOT NULL", (listing,))

    sent = []
    summary = alerts.run_alerts(conn, lambda to, subject, html: sent.append((to, subject, html)), "https://internlink.test")
    mine = [item for item in sent if f"/internships/{listing}" in item[2]]
    assert mine and "1 new internship for you" in mine[0][1]
    assert summary["emails"] >= 1
    # Running again sends nothing new for this student.
    sent.clear()
    alerts.run_alerts(conn, lambda to, subject, html: sent.append(to), "https://internlink.test")
    email = conn.execute("SELECT email FROM users WHERE user_id = %s", (student["user_id"],)).fetchone()["email"]
    assert email not in sent


def test_failed_alert_email_is_retried_next_time(conn):
    student = a_student(conn)
    alerts.create_alert(conn, student["student_id"], {})
    conn.execute("UPDATE job_alerts SET last_checked_at = now() - interval '400 days' WHERE student_id = %s", (student["student_id"],))
    email = conn.execute("SELECT email FROM users WHERE user_id = %s", (student["user_id"],)).fetchone()["email"]

    def failing(to, subject, html):
        if to == email:
            raise RuntimeError("mail server down")

    assert alerts.run_alerts(conn, failing, "https://x")["failed"] >= 1
    sent = []
    alerts.run_alerts(conn, lambda to, subject, html: sent.append(to), "https://x")
    assert email in sent


# ---------- coordinator invites ----------

def test_invite_accept_and_sign_in(conn):
    result = invites.invite_coordinator(conn, 1, {"email": "New.Coord@must.ac.ug", "department_id": 1}, "invite-token", inviter_name="Admin")
    assert result["email"] == "new.coord@must.ac.ug" and result["university"].startswith("Mbarara")
    details = invites.invite_details(conn, "invite-token")
    assert details == {"email": "new.coord@must.ac.ug", "university": result["university"], "department": "Software Engineering"}
    listed = {row["email"]: row for row in invites.list_coordinators(conn, 1)}
    assert listed["new.coord@must.ac.ug"]["invited"] and listed["new.coord@must.ac.ug"]["status"] == "pending"

    with pytest.raises(StudentError):
        invites.accept_invite(conn, "invite-token", {"full_name": "Okot James", "password": "short"})
    invites.accept_invite(conn, "invite-token", {"full_name": "Okot James", "password": "a-long-coordinator-pass"})
    user = authenticate_user(conn, "new.coord@must.ac.ug", "a-long-coordinator-pass")
    assert user["role"] == "coordinator"
    with pytest.raises(StudentError):  # the link only works once
        invites.accept_invite(conn, "invite-token", {"full_name": "X", "password": "another-long-password"})


def test_invite_rules(conn):
    with pytest.raises(StudentError) as error:  # wrong email domain
        invites.invite_coordinator(conn, 1, {"email": "someone@gmail.com"}, "t1", inviter_name="Admin")
    assert error.value.code == "UNIVERSITY_EMAIL_REQUIRED"
    with pytest.raises(StudentError) as error:  # university not verified yet
        invites.invite_coordinator(conn, 3, {"email": "x@kiu.ac.ug"}, "t2", inviter_name="Admin")
    assert error.value.code == "UNIVERSITY_NOT_VERIFIED"
    with pytest.raises(StudentError) as error:  # department of another university
        invites.invite_coordinator(conn, 1, {"email": "y@must.ac.ug", "department_id": 5}, "t3", inviter_name="Admin")
    assert error.value.status == 404
    with pytest.raises(StudentError) as error:  # existing account
        invites.invite_coordinator(conn, 1, {"email": "coord.se@must.ac.ug"}, "t4", inviter_name="Admin")
    assert error.value.code == "ALREADY_EXISTS"
    # Re-inviting the same pending person replaces the old link after the cooldown.
    invites.invite_coordinator(conn, 1, {"email": "z@must.ac.ug"}, "first", inviter_name="Admin")
    with pytest.raises(StudentError) as error:
        invites.invite_coordinator(conn, 1, {"email": "z@must.ac.ug"}, "second", inviter_name="Admin")
    assert error.value.status == 429
    conn.execute("UPDATE auth_tokens SET created_at = created_at - interval '5 minutes' WHERE purpose = 'coordinator_invite'")
    invites.invite_coordinator(conn, 1, {"email": "z@must.ac.ug"}, "second", inviter_name="Admin")
    with pytest.raises(StudentError):
        invites.invite_details(conn, "first")
    assert invites.invite_details(conn, "second")["email"] == "z@must.ac.ug"


def test_expired_invite_is_refused(conn):
    invites.invite_coordinator(conn, 1, {"email": "late@must.ac.ug"}, "late-token", inviter_name="Admin")
    conn.execute(
        "UPDATE auth_tokens SET created_at = now() - interval '9 days', expires_at = now() - interval '1 day' WHERE purpose = 'coordinator_invite'"
    )
    with pytest.raises(StudentError):
        invites.invite_details(conn, "late-token")


def test_verified_universities_list(conn):
    rows = invites.list_verified_universities(conn)
    must = next(row for row in rows if row["university_id"] == 1)
    assert must["active_coordinators"] >= 1 and must["students"] >= 1
    assert all(row["university_id"] != 3 for row in rows)  # pending university
