"""HTTP API behavior tests that do not require a PostgreSQL test database."""
import http.client
import json
import threading
from datetime import datetime, timedelta, timezone

import jwt
import pytest

import matching_engine.api as api

SECRET = "test-secret-at-least-32-bytes-long!!"
URL = "/api/v1/students/me/recommendations"


@pytest.fixture
def api_address(monkeypatch):
    class FakePool:
        def __init__(self, dsn, *, min_size, max_size, open):
            self.settings = (dsn, min_size, max_size)
            self.is_open = open

        def open(self, wait=False):
            self.is_open = wait

        def close(self):
            self.is_open = False

        def connection(self):
            raise AssertionError("Database access is not expected in these tests")

    monkeypatch.setattr(api, "ConnectionPool", FakePool)
    server = api.create_server(dsn="test", jwt_secret=SECRET, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def _request(address, path, headers=None):
    connection = http.client.HTTPConnection(*address)
    try:
        connection.request("GET", path, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.getheaders(), json.loads(response.read())
    finally:
        connection.close()


def _token(role="student"):
    claims = {
        "sub": "10",
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
    }
    return jwt.encode(claims, SECRET, algorithm="HS256")


def test_missing_token_returns_401_with_bearer_challenge(api_address):
    status, headers, body = _request(api_address, URL)

    assert status == 401
    assert ("WWW-Authenticate", "Bearer") in headers
    assert body == {"detail": "Not logged in"}


def test_non_student_token_returns_403(api_address):
    status, _, body = _request(
        api_address, URL, {"Authorization": f"Bearer {_token(role='employer')}"}
    )

    assert status == 403
    assert body == {"detail": "Only students can get recommendations"}


@pytest.mark.parametrize("limit", ["0", "51", "ten"])
def test_invalid_limit_returns_422_before_database_access(api_address, limit):
    status, _, body = _request(
        api_address,
        f"{URL}?limit={limit}",
        {"Authorization": f"Bearer {_token()}"},
    )

    assert status == 422
    assert body == {"detail": "Invalid limit"}
