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


class VercelEntryPointTests(unittest.TestCase):
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

    def test_unknown_route_returns_not_found(self):
        status, _, body = self.request("/not-an-api-route")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["detail"], "Not Found")


if __name__ == "__main__":
    unittest.main()
