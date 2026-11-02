"""WSGI API integration, HTTP mapping and binary CV tests."""

import unittest
from datetime import date, timedelta

from tests.support import (
    add_application,
    add_company,
    add_employer,
    add_employer_account,
    add_listing,
    add_student,
    call_api,
    make_context,
    seed_reference,
    session_for,
)


def api_registration(**overrides):
    form = {
        "company_name": "API Company",
        "sector": "Technology",
        "location": "Kampala",
        "contact_email": "api-hr@example.com",
        "rep_full_name": "API Person",
        "rep_email": "api-person@example.com",
        "password": "StrongPass1",
    }
    form.update(overrides)
    return form


class PublicApiTests(unittest.TestCase):
    def setUp(self):
        self.h = make_context()

    def tearDown(self):
        self.h.db.close()

    def test_register_verify_and_validation_over_http(self):
        response = call_api(self.h.api, "/api/employer/register", api_registration())
        self.assertEqual(response.status, 200)
        self.assertTrue(response.json["ok"])
        raw_token = self.h.mailer.sent[0]["body"].rsplit("=", 1)[1]

        invalid = call_api(
            self.h.api,
            "/api/employer/register",
            api_registration(
                company_name="Another Company",
                rep_email="bad-email",
                password="weak",
            ),
        )
        self.assertEqual(invalid.status, 400)
        self.assertEqual(invalid.json["fields"]["rep_email"], "Invalid email")

        self.assertEqual(
            call_api(self.h.api, "/api/employer/verify-email", {"token": raw_token}).status,
            200,
        )
        self.assertEqual(
            call_api(self.h.api, "/api/employer/verify-email", {"token": raw_token}).status,
            400,
        )
        self.assertEqual(
            call_api(self.h.api, "/api/employer/verify-email", {}).status, 400
        )

    def test_malformed_payloads_and_routing(self):
        bad_json = call_api(
            self.h.api, "/api/employer/register", raw_body="{not json"
        )
        self.assertEqual(bad_json.status, 400)
        self.assertEqual(bad_json.json["category"], "invalid")

        array_json = call_api(
            self.h.api, "/api/employer/register", raw_body="[1,2,3]"
        )
        self.assertEqual(array_json.status, 400)

        too_large = call_api(
            self.h.api,
            "/api/employer/register",
            payload={},
            content_length="99999999",
        )
        self.assertEqual(too_large.status, 413)

        not_found = call_api(self.h.api, "/nope", {})
        self.assertEqual(not_found.status, 404)
        self.assertEqual(not_found.json["category"], "not_found")

        empty_action = call_api(self.h.api, "/api/employer/", {})
        self.assertEqual(empty_action.status, 404)

        get_response = call_api(self.h.api, "/api/employer/register", method="GET")
        self.assertEqual(get_response.status, 405)
        self.assertEqual(get_response.headers["Allow"], "POST")

        for response in (bad_json, array_json, not_found, get_response):
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(response.headers["Cache-Control"], "no-store")


class AuthenticatedApiTests(unittest.TestCase):
    def setUp(self):
        self.h = make_context({"cvs/api.pdf": b"api cv bytes"})
        self.refs = seed_reference(self.h.db)
        self.company_id, self.user_id = add_employer_account(self.h.db)
        self.session, self.token = session_for(self.h, self.user_id)

    def tearDown(self):
        self.h.db.close()

    def test_authentication_and_authorization_mapping(self):
        self.assertEqual(call_api(self.h.api, "/api/employer/get_company", {}).status, 401)
        self.assertEqual(
            call_api(
                self.h.api, "/api/employer/get_company", {}, token="garbage"
            ).status,
            401,
        )

        student_id = add_student(self.h.db, self.refs)
        from tests.support import student_user_id

        student_token = self.h.auth.issue_token(student_user_id(self.h.db, student_id))
        self.assertEqual(
            call_api(
                self.h.api, "/api/employer/get_company", {}, token=student_token
            ).status,
            403,
        )

        response = call_api(self.h.api, "/api/employer/get_company", {}, token=self.token)
        self.assertEqual(response.status, 200)
        self.assertTrue(response.json["ok"])
        self.assertEqual(response.json["data"]["company"]["company_id"], self.company_id)
        self.assertEqual(response.json["data"]["company"]["verification_status"], "verified")

    def test_business_error_status_mapping(self):
        missing = call_api(
            self.h.api, "/api/employer/listing_detail", {}, token=self.token
        )
        self.assertEqual(missing.status, 400)
        self.assertEqual(missing.json["fields"]["listing_id"], "Required")

        not_found = call_api(
            self.h.api,
            "/api/employer/listing_detail",
            {"listing_id": 999},
            token=self.token,
        )
        self.assertEqual(not_found.status, 404)

        unknown = call_api(
            self.h.api, "/api/employer/no_such_action", {}, token=self.token
        )
        self.assertEqual(unknown.status, 400)
        self.assertEqual(unknown.json["category"], "invalid")

        invalid = call_api(
            self.h.api,
            "/api/employer/create_listing",
            {"title": ""},
            token=self.token,
        )
        self.assertEqual(invalid.status, 400)
        self.assertIn("title", invalid.json["fields"])

    def test_forbidden_and_conflict_status_mapping(self):
        pending_company = add_company(self.h.db, verification_status="pending")
        pending_user = add_employer(
            self.h.db, pending_company, email="api-pending@example.com"
        )
        pending_session, pending_token = session_for(self.h, pending_user)
        draft = add_listing(
            self.h.db, pending_company, pending_user, self.refs, status="draft"
        )
        forbidden = call_api(
            self.h.api,
            "/api/employer/set_listing_status",
            {"listing_id": draft, "status": "open"},
            token=pending_token,
        )
        self.assertEqual(forbidden.status, 403)

        draft2 = add_listing(
            self.h.db, self.company_id, self.user_id, self.refs, status="draft"
        )
        conflict = call_api(
            self.h.api,
            "/api/employer/set_listing_status",
            {"listing_id": draft2, "status": "closed"},
            token=self.token,
        )
        self.assertEqual(conflict.status, 409)

    def test_cv_download_returns_binary_not_json(self):
        listing_id = add_listing(self.h.db, self.company_id, self.user_id, self.refs)
        student_id = add_student(self.h.db, self.refs, cv_path="cvs/api.pdf")
        application_id = add_application(self.h.db, listing_id, student_id)
        response = call_api(
            self.h.api,
            "/api/employer/download_cv",
            {"application_id": application_id},
            token=self.token,
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Content-Type"], "application/octet-stream")
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertEqual(response.body, b"api cv bytes")

    def test_each_request_uses_its_own_session(self):
        company_two, user_two = add_employer_account(
            self.h.db, name="Second API Co", email="second-api@example.com"
        )
        _, token_two = session_for(self.h, user_two)
        first = call_api(self.h.api, "/api/employer/get_company", {}, token=self.token)
        second = call_api(self.h.api, "/api/employer/get_company", {}, token=token_two)
        self.assertEqual(first.json["data"]["company"]["company_id"], self.company_id)
        self.assertEqual(second.json["data"]["company"]["company_id"], company_two)

    def test_listing_actions_over_http(self):
        form = {
            "title": "API Listing",
            "description": "Created through the API",
            "sector": "Technology",
            "location": "Kampala",
            "duration_weeks": 12,
            "slots": 2,
            "application_deadline": (date.today() + timedelta(days=10)).isoformat(),
        }
        created = call_api(
            self.h.api, "/api/employer/create_listing", form, token=self.token
        )
        self.assertEqual(created.status, 200)
        listing_id = created.json["data"]["listing_id"]

        opened = call_api(
            self.h.api,
            "/api/employer/set_listing_status",
            {"listing_id": listing_id, "status": "open"},
            token=self.token,
        )
        self.assertEqual(opened.status, 200)
        self.assertEqual(opened.json["data"]["status"], "open")

        listing = call_api(
            self.h.api,
            "/api/employer/my_listings",
            {"search": "API"},
            token=self.token,
        )
        self.assertEqual(listing.status, 200)
        self.assertEqual(listing.json["data"][0]["listing_id"], listing_id)


if __name__ == "__main__":
    unittest.main()
