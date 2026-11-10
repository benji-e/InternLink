import json
import os
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import jwt

from api.index import handler


class ServerTestCase(unittest.TestCase):
    """Runs the Vercel handler on a local port for each test."""

    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path, *, method="GET", body=None, headers=None):
        request = Request(
            self.base_url + path,
            data=body,
            headers=headers or {},
            method=method,
        )
        try:
            response = urlopen(request, timeout=2)
        except HTTPError as error:
            response = error
        return response.status, response.headers, response.read()

    def post_json(self, path, payload):
        return self.request(
            path,
            method="POST",
            body=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )


class VercelEntryPointTests(ServerTestCase):
    def test_root_is_health_check(self):
        status, _, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertEqual(
            json.loads(body),
            {"service": "InternLink API", "status": "ok"},
        )

    def test_api_health_route_is_available(self):
        status, _, body = self.request("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "ok")

    def test_recommendations_require_a_bearer_token(self):
        with patch.dict(os.environ, {"INTERNLINK_JWT_SECRET": "test-secret"}):
            status, headers, body = self.request(
                "/api/v1/students/me/recommendations"
            )
        self.assertEqual(status, 401)
        self.assertEqual(headers["WWW-Authenticate"], "Bearer")
        self.assertEqual(json.loads(body)["detail"], "Not logged in")

    def test_employer_route_reports_missing_configuration(self):
        names = ("INTERNLINK_DSN", "INTERNLINK_JWT_SECRET")
        with patch.dict(os.environ, {name: "" for name in names}):
            status, _, body = self.request(
                "/api/employer/register",
                method="POST",
                body=b"{}",
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)["message"], "INTERNLINK_JWT_SECRET must contain at least 32 characters.")

    def test_student_token_cannot_access_administrator_api(self):
        secret = "test-signing-secret-that-is-at-least-32-characters"
        token = jwt.encode(
            {"sub": "25", "role": "student", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
            secret,
            algorithm="HS256",
        )
        with patch.dict(os.environ, {"INTERNLINK_JWT_SECRET": secret}):
            status, _, body = self.request(
                "/api/v1/admin/users",
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"]["code"], "ROLE_REQUIRED")

    def test_student_token_cannot_manage_university_catalog(self):
        secret = "test-signing-secret-that-is-at-least-32-characters"
        token = jwt.encode(
            {"sub": "25", "role": "student", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
            secret,
            algorithm="HS256",
        )
        with patch.dict(os.environ, {"INTERNLINK_JWT_SECRET": secret}):
            for method, path in (
                ("GET", "/api/v1/coordinator/catalog"),
                ("POST", "/api/v1/coordinator/departments"),
                ("POST", "/api/v1/coordinator/programmes"),
            ):
                status, _, body = self.request(
                    path,
                    method=method,
                    body=b"{}" if method == "POST" else None,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                )
                self.assertEqual(status, 403, path)
                self.assertEqual(json.loads(body)["error"]["code"], "ROLE_REQUIRED")

    def test_catalog_write_routes_only_accept_post(self):
        for path in ("/api/v1/coordinator/departments", "/api/v1/coordinator/programmes"):
            status, headers, _ = self.request(path)
            self.assertEqual(status, 405, path)
            self.assertEqual(headers["Allow"], "POST")

    def test_alert_cron_needs_its_secret(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CRON_SECRET", None)
            status, _, _ = self.request("/api/cron/job-alerts")
            self.assertEqual(status, 503)
        with patch.dict(os.environ, {"CRON_SECRET": "cron-secret-value"}):
            status, _, _ = self.request("/api/cron/job-alerts", headers={"Authorization": "Bearer wrong"})
            self.assertEqual(status, 401)

    def test_cv_upload_is_size_checked_before_reading(self):
        status, _, body = self.request(
            "/api/v1/students/me/cv",
            method="PUT",
            body=b"x",
            headers={"Content-Length": str(5 * 1024 * 1024), "Content-Type": "application/pdf"},
        )
        self.assertEqual(status, 413)
        self.assertEqual(json.loads(body)["error"]["code"], "FILE_TOO_LARGE")
        self.assertIn("4 MB", json.loads(body)["error"]["message"])

    def test_unknown_route_returns_not_found(self):
        status, _, body = self.request("/not-an-api-route")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["detail"], "Not Found")


class AccountEndpointTests(ServerTestCase):
    """Sign-up and recovery endpoints, with the database and email faked."""

    EMAIL_ENV = {"RESEND_API_KEY": "re_test", "INTERNLINK_FROM_EMAIL": "noreply@internlink.test"}

    def fake_database(self):
        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def transaction(self):
                return self

        return patch.object(handler, "_student_connection", lambda _self: FakeConnection())

    def test_account_email_endpoints_need_email_configuration(self):
        paths = (
            "/api/v1/auth/forgot-password",
            "/api/v1/auth/resend-verification",
            "/api/v1/auth/register-university",
        )
        with patch.dict(os.environ, {"RESEND_API_KEY": "", "INTERNLINK_FROM_EMAIL": ""}):
            for path in paths:
                with self.subTest(path=path):
                    status, _, body = self.post_json(path, {"email": "someone@example.com"})
                    self.assertEqual(status, 503)
                    self.assertEqual(json.loads(body)["error"]["code"], "CONFIGURATION_ERROR")

    def test_recovery_endpoints_only_accept_post(self):
        for path in ("/api/v1/auth/forgot-password", "/api/v1/auth/reset-password", "/api/v1/auth/resend-verification"):
            with self.subTest(path=path):
                status, _, _ = self.request(path)
                self.assertEqual(status, 405)

    def test_forgot_password_answers_the_same_whether_or_not_the_account_exists(self):
        recipient = {"email": "known@example.com", "full_name": "Known User", "role": "student"}
        sent = []
        with patch.dict(os.environ, self.EMAIL_ENV), self.fake_database(), patch(
            "api.index.account_service.create_password_reset", side_effect=[None, recipient]
        ), patch.object(handler, "_send_email", staticmethod(lambda to, subject, html: sent.append((to, html)))):
            unknown = self.post_json("/api/v1/auth/forgot-password", {"email": "unknown@example.com"})
            known = self.post_json("/api/v1/auth/forgot-password", {"email": "known@example.com"})

        self.assertEqual((unknown[0], unknown[2]), (known[0], known[2]))
        self.assertEqual(known[0], 202)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], "known@example.com")
        self.assertIn("/reset-password?token=", sent[0][1])

    def test_failed_email_delivery_does_not_reveal_the_account(self):
        from api.index import ConfigurationError

        def fail(*_args):
            raise ConfigurationError("provider down")

        recipient = {"email": "known@example.com", "full_name": "Known User", "role": "employer"}
        with patch.dict(os.environ, self.EMAIL_ENV), self.fake_database(), patch(
            "api.index.account_service.create_email_verification", return_value=recipient
        ), patch.object(handler, "_send_email", staticmethod(fail)):
            status, _, body = self.post_json("/api/v1/auth/resend-verification", {"email": "known@example.com"})
        self.assertEqual(status, 202)
        self.assertIn("If an account matches", json.loads(body)["message"])

    def test_verification_links_point_to_the_right_page_for_each_role(self):
        with patch.dict(os.environ, {"INTERNLINK_PUBLIC_BASE_URL": "https://internlink.test/"}):
            self.assertEqual(handler._verification_url("employer", "abc"), "https://internlink.test/verify-email?token=abc")
            self.assertEqual(handler._verification_url("student", "abc"), "https://internlink.test/verify?token=abc")
            self.assertEqual(handler._verification_url("coordinator", "abc"), "https://internlink.test/verify?token=abc")


if __name__ == "__main__":
    unittest.main()
