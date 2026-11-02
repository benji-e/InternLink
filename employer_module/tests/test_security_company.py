"""Security, registration, email verification and company profile tests."""

import unittest
from datetime import timedelta

from internlink_employer.errors import ModuleError
from internlink_employer.security import (
    ReferenceTokenService,
    hash_password,
    verify_password,
)
from internlink_employer.services import (
    get_company_status,
    register_employer,
    update_company_profile,
    verify_employer_email,
)
from internlink_employer.session import Session, open_session
from tests.support import (
    SECRET,
    add_company,
    add_employer,
    add_employer_account,
    add_student,
    make_context,
    seed_reference,
    session_for,
)


def registration_form(**overrides):
    form = {
        "company_name": "Acme Uganda",
        "sector": "Technology",
        "location": "Kampala",
        "description": "We build things.",
        "website": "https://acme.example",
        "contact_email": "HR@Acme.Example",
        "rep_full_name": "Ada Lovelace",
        "rep_email": "Ada@Acme.Example",
        "rep_phone": "+256700111222",
        "password": "StrongPass1",
    }
    form.update(overrides)
    return form


class PasswordAndTokenTests(unittest.TestCase):
    def test_password_hash_round_trip_and_salts(self):
        first = hash_password("StrongPass1")
        second = hash_password("StrongPass1")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("StrongPass1", first))
        self.assertTrue(verify_password("StrongPass1", second))
        self.assertFalse(verify_password("strongpass1", first))
        self.assertFalse(verify_password("StrongPass1", "garbage"))
        self.assertFalse(verify_password("StrongPass1", "pbkdf2_sha256$x$y$z"))
        with self.assertRaises(ValueError):
            hash_password("")

    def test_reference_tokens_verify_expire_and_reject_tampering(self):
        with self.assertRaises(ValueError):
            ReferenceTokenService("too-short")
        service = ReferenceTokenService(SECRET)
        token = service.issue_token(42, role="employer")
        claims = service.verify_token(token)
        self.assertEqual(claims["user_id"], 42)
        self.assertEqual(claims["role"], "employer")

        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        self.assertIsNone(service.verify_token(tampered))
        self.assertIsNone(service.verify_token("not-a-token"))
        self.assertIsNone(service.verify_token(None))
        self.assertIsNone(service.verify_token(""))

        expired = service.issue_token(42, ttl=timedelta(seconds=-1))
        self.assertIsNone(service.verify_token(expired))


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.h = make_context()

    def tearDown(self):
        self.h.db.close()

    def test_registration_validation_reports_every_bad_field(self):
        with self.assertRaises(ModuleError) as caught:
            register_employer(self.h.db, self.h.mailer, {})
        error = caught.exception
        self.assertEqual(error.category, "invalid")
        for field in (
            "company_name",
            "sector",
            "location",
            "contact_email",
            "rep_full_name",
            "rep_email",
            "password",
        ):
            self.assertIn(field, error.fields)

        with self.assertRaises(ModuleError) as caught:
            register_employer(
                self.h.db,
                self.h.mailer,
                registration_form(
                    contact_email="not-an-email",
                    rep_email="also bad",
                    password="weakpass",
                    company_name="x" * 151,
                ),
            )
        fields = caught.exception.fields
        self.assertEqual(fields["contact_email"], "Invalid email")
        self.assertEqual(fields["rep_email"], "Invalid email")
        self.assertIn("upper", fields["password"])
        self.assertIn("at most", fields["company_name"])

        with self.assertRaises(ModuleError):
            register_employer(self.h.db, self.h.mailer, ["not", "a", "mapping"])

    def test_registration_creates_pending_company_user_and_hashed_token(self):
        result = register_employer(
            self.h.db,
            self.h.mailer,
            registration_form(),
            base_url="https://internlink.test/",
        )
        company = self.h.db.query_one(
            "SELECT * FROM companies WHERE company_id = %s", [result["company_id"]]
        )
        user = self.h.db.query_one(
            "SELECT * FROM users WHERE company_id = %s", [result["company_id"]]
        )
        token = self.h.db.query_one(
            "SELECT * FROM auth_tokens WHERE user_id = %s", [user["user_id"]]
        )

        self.assertEqual(company["verification_status"], "pending")
        self.assertEqual(company["contact_email"], "hr@acme.example")
        self.assertEqual(user["status"], "pending")
        self.assertEqual(user["role"], "employer")
        self.assertEqual(user["email"], "ada@acme.example")
        self.assertNotEqual(user["password_hash"], "StrongPass1")
        self.assertTrue(verify_password("StrongPass1", user["password_hash"]))
        self.assertEqual(token["purpose"], "email_verify")
        self.assertEqual(len(token["token_hash"]), 64)

        self.assertEqual(len(self.h.mailer.sent), 1)
        message = self.h.mailer.sent[0]
        self.assertEqual(message["to"], "ada@acme.example")
        self.assertIn("https://internlink.test/verify-email?token=", message["body"])
        raw_token = message["body"].rsplit("=", 1)[1]
        self.assertNotEqual(token["token_hash"], raw_token)

    def test_duplicate_company_or_email_is_conflict(self):
        register_employer(self.h.db, self.h.mailer, registration_form())
        with self.assertRaises(ModuleError) as caught:
            register_employer(
                self.h.db,
                self.h.mailer,
                registration_form(rep_email="other@acme.example"),
            )
        self.assertEqual(caught.exception.category, "conflict")

        with self.assertRaises(ModuleError) as caught:
            register_employer(
                self.h.db,
                self.h.mailer,
                registration_form(company_name="Different Co"),
            )
        self.assertEqual(caught.exception.category, "conflict")

    def test_verify_email_activates_user_once_and_rejects_expired_or_bad_tokens(self):
        register_employer(self.h.db, self.h.mailer, registration_form())
        raw_token = self.h.mailer.sent[0]["body"].rsplit("=", 1)[1]

        self.assertIn("verified", verify_employer_email(self.h.db, raw_token)["message"])
        user = self.h.db.query_one("SELECT * FROM users")
        self.assertEqual(user["status"], "active")
        self.assertIsNotNone(user["email_verified_at"])
        token = self.h.db.query_one("SELECT * FROM auth_tokens")
        self.assertIsNotNone(token["used_at"])
        company = self.h.db.query_one("SELECT * FROM companies")
        self.assertEqual(company["verification_status"], "pending")

        with self.assertRaises(ModuleError):
            verify_employer_email(self.h.db, raw_token)
        with self.assertRaises(ModuleError):
            verify_employer_email(self.h.db, None)
        with self.assertRaises(ModuleError):
            verify_employer_email(self.h.db, "made-up-token")

    def test_verification_does_not_reactivate_a_suspended_account(self):
        register_employer(self.h.db, self.h.mailer, registration_form())
        raw_token = self.h.mailer.sent[0]["body"].rsplit("=", 1)[1]
        self.h.db.execute("UPDATE users SET status = 'suspended'")
        verify_employer_email(self.h.db, raw_token)
        user = self.h.db.query_one("SELECT status, email_verified_at FROM users")
        self.assertEqual(user["status"], "suspended")
        self.assertIsNotNone(user["email_verified_at"])

    def test_verify_email_rejects_expired_token(self):
        register_employer(self.h.db, self.h.mailer, registration_form())
        raw_token = self.h.mailer.sent[0]["body"].rsplit("=", 1)[1]
        self.h.db.execute(
            "UPDATE auth_tokens SET expires_at = %s",
            ["2000-01-01 00:00:00"],
        )
        with self.assertRaises(ModuleError):
            verify_employer_email(self.h.db, raw_token)
        user = self.h.db.query_one("SELECT status FROM users")
        self.assertEqual(user["status"], "pending")


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.h = make_context()
        self.refs = seed_reference(self.h.db)
        self.company_id, self.user_id = add_employer_account(self.h.db)

    def tearDown(self):
        self.h.db.close()

    def test_missing_bad_and_student_tokens_are_rejected(self):
        with self.assertRaises(ModuleError) as caught:
            open_session(self.h.db, self.h.auth, None)
        self.assertEqual(caught.exception.category, "unauthenticated")

        with self.assertRaises(ModuleError) as caught:
            open_session(self.h.db, self.h.auth, "garbage")
        self.assertEqual(caught.exception.category, "unauthenticated")

        student_id = add_student(self.h.db, self.refs)
        from tests.support import student_user_id

        token = self.h.auth.issue_token(student_user_id(self.h.db, student_id))
        with self.assertRaises(ModuleError) as caught:
            open_session(self.h.db, self.h.auth, token)
        self.assertEqual(caught.exception.category, "forbidden")
        audit = self.h.db.query_one(
            "SELECT * FROM audit_log WHERE action = 'access_denied'"
        )
        self.assertEqual(audit["result"], "denied")

    def test_inactive_employer_account_is_rejected(self):
        _, user_id = add_employer_account(
            self.h.db, email="pending@example.com", status="pending"
        )
        token = self.h.auth.issue_token(user_id)
        with self.assertRaises(ModuleError) as caught:
            open_session(self.h.db, self.h.auth, token)
        self.assertEqual(caught.exception.category, "forbidden")
        audit = self.h.db.query_one(
            "SELECT * FROM audit_log WHERE action = 'access_denied'"
        )
        self.assertEqual(audit["result"], "denied")

    def test_active_employer_with_pending_company_can_log_in(self):
        company_id = add_company(self.h.db, verification_status="pending")
        user_id = add_employer(self.h.db, company_id)
        token = self.h.auth.issue_token(user_id)
        session = open_session(self.h.db, self.h.auth, token)
        self.assertEqual(session.company_id, company_id)
        self.assertEqual(session.role, "employer")

    def test_session_company_comes_from_database(self):
        session = open_session(
            self.h.db, self.h.auth, self.h.auth.issue_token(self.user_id)
        )
        self.assertEqual(session.company_id, self.company_id)
        self.assertEqual(session.user_id, self.user_id)
        self.assertIsInstance(session, Session)


class CompanyProfileTests(unittest.TestCase):
    def setUp(self):
        self.h = make_context()
        self.refs = seed_reference(self.h.db)
        self.company_id, self.user_id = add_employer_account(self.h.db)
        self.session, self.token = session_for(self.h, self.user_id)

    def tearDown(self):
        self.h.db.close()

    def test_status_banners_and_publish_flag(self):
        self.assertEqual(get_company_status(self.h.db, self.session)["banner"], None)
        self.assertTrue(get_company_status(self.h.db, self.session)["can_publish"])

        self.h.db.execute(
            "UPDATE companies SET verification_status = 'pending' WHERE company_id = %s",
            [self.company_id],
        )
        status = get_company_status(self.h.db, self.session)
        self.assertFalse(status["can_publish"])
        self.assertIn("Awaiting administrator", status["banner"])

        self.h.db.execute(
            """
            UPDATE companies
            SET verification_status = 'rejected', rejection_reason = 'Missing documents'
            WHERE company_id = %s
            """,
            [self.company_id],
        )
        status = get_company_status(self.h.db, self.session)
        self.assertFalse(status["can_publish"])
        self.assertIn("Missing documents", status["banner"])

        self.h.db.execute(
            "UPDATE companies SET verification_status = 'suspended' WHERE company_id = %s",
            [self.company_id],
        )
        self.assertIn("suspended", get_company_status(self.h.db, self.session)["banner"])

    def test_update_profile_only_changes_editable_fields(self):
        original = self.h.db.query_one(
            "SELECT * FROM companies WHERE company_id = %s", [self.company_id]
        )
        result = update_company_profile(
            self.h.db,
            self.session,
            {
                "sector": "Fintech",
                "location": "Entebbe",
                "description": "Updated description",
                "contact_email": "HELLO@Example.COM",
                "website": "https://new.example",
                "name": "Hacked name",
                "verification_status": "verified",
            },
        )
        company = result["company"]
        self.assertEqual(company["sector"], "Fintech")
        self.assertEqual(company["location"], "Entebbe")
        self.assertEqual(company["contact_email"], "hello@example.com")
        self.assertEqual(company["name"], original["name"])
        self.assertEqual(company["verification_status"], "verified")
        audit = self.h.db.query_one(
            "SELECT * FROM audit_log WHERE action = 'company_profile_updated'"
        )
        self.assertEqual(audit["actor_user_id"], self.user_id)

    def test_update_profile_validation_and_missing_company(self):
        with self.assertRaises(ModuleError) as caught:
            update_company_profile(
                self.h.db,
                self.session,
                {"sector": "", "location": "Kampala", "contact_email": "bad"},
            )
        self.assertIn("sector", caught.exception.fields)
        self.assertIn("contact_email", caught.exception.fields)

        fake_session = Session(99, "employer", "active", 9999)
        with self.assertRaises(ModuleError) as caught:
            get_company_status(self.h.db, fake_session)
        self.assertEqual(caught.exception.category, "not_found")


if __name__ == "__main__":
    unittest.main()
