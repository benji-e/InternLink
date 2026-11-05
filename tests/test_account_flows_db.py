"""Self-service account flows: university sign-up, resend verification, password reset.

Integration tests. They need PostgreSQL 16 with 01_schema, 02_functions_triggers,
03_views_functions and 05_seed loaded, and INTERNLINK_TEST_DSN set. Skipped
otherwise. Every test runs in a transaction that is rolled back.
"""
import hashlib
import os

import pytest

from student_module import accounts
from student_module.service import StudentError, authenticate_user, register_student

DSN = os.environ.get("INTERNLINK_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="INTERNLINK_TEST_DSN not set (no test database)")

NEW_UNIVERSITY = {
    "university_name": "Gulu University",
    "location": "Gulu",
    "email_domain": "gu.ac.ug",
    "full_name": "Okello Grace",
    "email": "internships@gu.ac.ug",
    "password": "a-long-coordinator-password",
}


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


def one(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()


def age_tokens(conn, user_id):
    """Move a user's tokens out of the resend cooldown."""
    conn.execute(
        "UPDATE auth_tokens SET created_at = created_at - interval '5 minutes' WHERE user_id = %s",
        (user_id,),
    )


def new_student(conn, email="new.student@std.must.ac.ug", token="student-verify-token"):
    account = register_student(
        conn,
        {
            "full_name": "Atim Joan",
            "email": email,
            "password": "a-long-student-password",
            "student_number": "2026/BSE/999",
            "university_id": 1,
            "department_id": 1,
            "programme_id": 1,
            "year_of_study": 2,
        },
        token,
    )
    return account["user_id"]


# ---- University sign-up -------------------------------------------------------

def test_university_signup_creates_pending_university_and_coordinator(conn):
    result = accounts.register_university(conn, dict(NEW_UNIVERSITY), "uni-token")

    university = one(conn, "SELECT status, email_domain FROM universities WHERE university_id = %s", (result["university_id"],))
    assert university == {"status": "pending", "email_domain": "gu.ac.ug"}
    user = one(conn, "SELECT role, status, university_id FROM users WHERE user_id = %s", (result["user_id"],))
    assert user == {"role": "coordinator", "status": "pending", "university_id": result["university_id"]}
    queued = one(conn, "SELECT org_type FROM v_admin_pending_registrations WHERE org_type = 'university' AND org_id = %s", (result["university_id"],))
    assert queued is not None


def test_university_signup_accepts_domain_written_with_at_sign(conn):
    result = accounts.register_university(conn, {**NEW_UNIVERSITY, "email_domain": "@GU.ac.ug"}, "uni-token")
    assert one(conn, "SELECT email_domain FROM universities WHERE university_id = %s", (result["university_id"],))["email_domain"] == "gu.ac.ug"


def test_university_signup_requires_staff_email_at_the_domain(conn):
    with pytest.raises(StudentError) as error:
        accounts.register_university(conn, {**NEW_UNIVERSITY, "email": "grace@gmail.com"}, "uni-token")
    assert error.value.code == "UNIVERSITY_EMAIL_REQUIRED"


def test_university_signup_rejects_an_existing_university(conn):
    with pytest.raises(StudentError) as error:
        accounts.register_university(
            conn, {**NEW_UNIVERSITY, "email_domain": "must.ac.ug", "email": "someone@must.ac.ug"}, "uni-token"
        )
    assert error.value.status == 409
    assert error.value.code == "UNIVERSITY_EXISTS"


def test_coordinator_waits_for_admin_then_is_activated(conn):
    result = accounts.register_university(conn, dict(NEW_UNIVERSITY), "uni-token")

    verified = accounts.verify_account_email(conn, "uni-token")
    assert verified == {"verified": True, "role": "coordinator", "awaiting_review": True}
    assert one(conn, "SELECT status FROM users WHERE user_id = %s", (result["user_id"],))["status"] == "pending"

    conn.execute("SELECT set_config('app.user_id', '1', true)")
    conn.execute("UPDATE universities SET status = 'verified' WHERE university_id = %s", (result["university_id"],))
    assert accounts.activate_university_coordinators(conn, result["university_id"]) == 1
    assert one(conn, "SELECT status FROM users WHERE user_id = %s", (result["user_id"],))["status"] == "active"


def test_unconfirmed_coordinator_is_not_activated(conn):
    result = accounts.register_university(conn, dict(NEW_UNIVERSITY), "uni-token")
    conn.execute("SELECT set_config('app.user_id', '1', true)")
    conn.execute("UPDATE universities SET status = 'verified' WHERE university_id = %s", (result["university_id"],))
    assert accounts.activate_university_coordinators(conn, result["university_id"]) == 0


# ---- Email verification ------------------------------------------------------

def test_student_verification_still_activates_straight_away(conn):
    user_id = new_student(conn)
    assert accounts.verify_account_email(conn, "student-verify-token")["awaiting_review"] is False
    assert one(conn, "SELECT status FROM users WHERE user_id = %s", (user_id,))["status"] == "active"


def test_verification_link_works_only_once(conn):
    new_student(conn)
    accounts.verify_account_email(conn, "student-verify-token")
    with pytest.raises(StudentError):
        accounts.verify_account_email(conn, "student-verify-token")


def test_resend_replaces_the_old_link(conn):
    user_id = new_student(conn)
    age_tokens(conn, user_id)

    recipient = accounts.create_email_verification(conn, "New.Student@std.must.ac.ug", "fresh-token")
    assert recipient == {"email": "new.student@std.must.ac.ug", "full_name": "Atim Joan", "role": "student"}
    with pytest.raises(StudentError):
        accounts.verify_account_email(conn, "student-verify-token")
    accounts.verify_account_email(conn, "fresh-token")


def test_resend_is_skipped_during_cooldown(conn):
    new_student(conn)
    assert accounts.create_email_verification(conn, "new.student@std.must.ac.ug", "fresh-token") is None


@pytest.mark.parametrize("email", ["nobody@example.com", "coord.se@must.ac.ug", "not-an-email"])
def test_resend_sends_nothing_for_unknown_or_verified_accounts(conn, email):
    assert accounts.create_email_verification(conn, email, "fresh-token") is None


def test_resend_link_for_employer_expires_the_old_one(conn):
    """The employer module checks only used_at/expires_at, so old links must expire."""
    from employer_module.internlink_employer.security import hash_token

    company = one(conn, "INSERT INTO companies (name, sector, location, contact_email) VALUES ('Acme', 'Software', 'Kampala', 'hr@acme.example') RETURNING company_id")
    user = one(
        conn,
        "INSERT INTO users (email, password_hash, full_name, role, company_id) VALUES ('rep@acme.example', 'x' || repeat('y', 30), 'Rep', 'employer', %s) RETURNING user_id",
        (company["company_id"],),
    )
    conn.execute(
        "INSERT INTO auth_tokens (user_id, purpose, token_hash, expires_at, created_at) VALUES (%s, 'email_verify', %s, now() + interval '1 day', now() - interval '5 minutes')",
        (user["user_id"], hash_token("old-employer-token")),
    )

    assert accounts.create_email_verification(conn, "rep@acme.example", "new-employer-token")["role"] == "employer"
    old = one(conn, "SELECT expires_at <= now() AS expired FROM auth_tokens WHERE token_hash = %s", (hash_token("old-employer-token"),))
    assert old["expired"] is True
    # The employer module and this module must agree on the token hash.
    assert hash_token("new-employer-token") == hashlib.sha256(b"new-employer-token").hexdigest()


# ---- Password reset ----------------------------------------------------------

def test_password_reset_changes_the_password(conn):
    assert accounts.create_password_reset(conn, "coord.se@must.ac.ug", "reset-token")["role"] == "coordinator"

    result = accounts.reset_password(conn, "reset-token", "a-brand-new-password")
    assert result == {"reset": True, "awaiting_verification": False}
    assert authenticate_user(conn, "coord.se@must.ac.ug", "a-brand-new-password")["role"] == "coordinator"


def test_reset_link_works_only_once(conn):
    accounts.create_password_reset(conn, "coord.se@must.ac.ug", "reset-token")
    accounts.reset_password(conn, "reset-token", "a-brand-new-password")
    with pytest.raises(StudentError) as error:
        accounts.reset_password(conn, "reset-token", "another-new-password")
    assert error.value.code == "INVALID_RESET_TOKEN"


def test_reset_clears_a_login_lock(conn):
    conn.execute("UPDATE users SET failed_login_count = 5, locked_until = now() + interval '15 minutes' WHERE user_id = 2")
    accounts.create_password_reset(conn, "coord.se@must.ac.ug", "reset-token")
    accounts.reset_password(conn, "reset-token", "a-brand-new-password")
    assert one(conn, "SELECT failed_login_count, locked_until FROM users WHERE user_id = 2") == {"failed_login_count": 0, "locked_until": None}


def test_reset_rejects_a_short_password(conn):
    accounts.create_password_reset(conn, "coord.se@must.ac.ug", "reset-token")
    with pytest.raises(StudentError) as error:
        accounts.reset_password(conn, "reset-token", "short")
    assert error.value.code == "WEAK_PASSWORD"


def test_employer_reset_keeps_the_employer_password_rule_and_hash(conn):
    accounts.create_password_reset(conn, "hr@techco.example", "reset-token")
    with pytest.raises(StudentError):
        accounts.reset_password(conn, "reset-token", "alllowercase-no-digit")
    accounts.reset_password(conn, "reset-token", "NewEmployerPass1")
    stored = one(conn, "SELECT password_hash FROM users WHERE user_id = 5")["password_hash"]
    assert stored.startswith("pbkdf2_sha256$")
    assert authenticate_user(conn, "hr@techco.example", "NewEmployerPass1")["role"] == "employer"


def test_reset_for_unknown_or_suspended_account_sends_nothing(conn):
    assert accounts.create_password_reset(conn, "nobody@example.com", "reset-token") is None
    conn.execute("SELECT set_config('app.user_id', '1', true)")
    conn.execute("UPDATE users SET status = 'suspended' WHERE user_id = 2")
    assert accounts.create_password_reset(conn, "coord.se@must.ac.ug", "reset-token") is None


def test_unverified_account_can_reset_but_still_needs_to_confirm_email(conn):
    new_student(conn)
    accounts.create_password_reset(conn, "new.student@std.must.ac.ug", "reset-token")
    assert accounts.reset_password(conn, "reset-token", "a-brand-new-password")["awaiting_verification"] is True
