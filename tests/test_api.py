"""GET /api/v1/students/me/recommendations (WBS 4.6.2, design 3.4 Section 7).

Runs against the PR #2 seed database; skipped when INTERNLINK_TEST_DSN is not set.
"""
import http.client
import json
import os
import threading
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import jwt
import pytest

from matching_engine.api import create_server
from matching_engine.config import DEFAULT_CONFIG

DSN = os.environ.get("INTERNLINK_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="INTERNLINK_TEST_DSN not set (no test database)")

SECRET = "test-secret-at-least-32-bytes-long!!"
URL = "/api/v1/students/me/recommendations"
NAKATO_USER_ID = 10  # seed student 1


def token(user_id=NAKATO_USER_ID, role="student", secret=SECRET, expires_in=timedelta(minutes=15)):
    claims = {"sub": str(user_id), "role": role, "exp": datetime.now(timezone.utc) + expires_in}
    return jwt.encode(claims, secret, algorithm="HS256")


def auth(**kwargs):
    return {"Authorization": f"Bearer {token(**kwargs)}"}


class ApiResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return json.loads(self._body)


class ApiTestClient:
    def __init__(self, server):
        self.server = server
        self.thread = threading.Thread(target=server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = server.server_address

    def get(self, path, *, headers=None, params=None):
        if params:
            path = f"{path}?{urlencode(params)}"
        connection = http.client.HTTPConnection(self.host, self.port)
        try:
            connection.request("GET", path, headers=headers or {})
            response = connection.getresponse()
            return ApiResponse(response.status, response.read())
        finally:
            connection.close()

@contextmanager
def make_client(cfg=DEFAULT_CONFIG):
    server = create_server(dsn=DSN, jwt_secret=SECRET, cfg=cfg, port=0)
    client = ApiTestClient(server)
    try:
        yield client
    finally:
        server.shutdown()
        client.thread.join()
        server.server_close()


@pytest.fixture
def client():
    with make_client() as c:
        yield c


# ---- 200 ----------------------------------------------------------------------

def test_student_gets_ranked_recommendations(client):
    response = client.get(URL, headers=auth())
    assert response.status_code == 200
    body = response.json()
    assert body["algorithm"] == "fn_recommendations v1"
    assert body["count"] == 5
    top = body["results"][0]
    assert top["rank"] == 1
    assert top["listing_id"] == 1
    assert top["title"] == "Software Developer Intern"
    assert top["company"] == "TechCo Ltd"
    assert top["score"] == 79
    assert top["breakdown"] == {"programme": 1.0, "skills": 0.667, "interests": 0.5, "location": 1.0}
    assert top["applied"] is True
    assert top["matched_skills"] == ["Python", "SQL"]
    assert top["missing_skills"] == ["React"]
    assert len(top["deadline"]) == 10  # YYYY-MM-DD


def test_limit_shortens_the_list(client):
    assert client.get(URL, params={"limit": 2}, headers=auth()).json()["count"] == 2


@pytest.mark.parametrize("bad_limit", [0, 51, "ten"])
def test_limit_outside_1_to_50_is_rejected(client, bad_limit):
    assert client.get(URL, params={"limit": bad_limit}, headers=auth()).status_code == 422


# ---- 401 / 403 (SR17, NFR05) --------------------------------------------------

def test_no_token_gets_401(client):
    assert client.get(URL).status_code == 401


def test_token_signed_with_another_secret_gets_401(client):
    assert client.get(URL, headers=auth(secret="some-other-secret-that-is-32-bytes!")).status_code == 401


def test_expired_token_gets_401(client):
    assert client.get(URL, headers=auth(expires_in=timedelta(minutes=-1))).status_code == 401


@pytest.mark.parametrize("role", ["employer", "coordinator", "admin"])
def test_non_student_roles_get_403(client, role):
    assert client.get(URL, headers=auth(user_id=5, role=role)).status_code == 403


# ---- 422 / 503 ----------------------------------------------------------------

def test_student_without_profile_gets_422_profile_incomplete(client):
    response = client.get(URL, headers=auth(user_id=999_999))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PROFILE_INCOMPLETE"


def test_slow_database_gets_503_without_internal_details():
    import psycopg

    with make_client(replace(DEFAULT_CONFIG, timeout_seconds=0.5)) as client:
        with psycopg.connect(DSN) as locker:
            locker.execute("LOCK TABLE listings IN ACCESS EXCLUSIVE MODE")
            response = client.get(URL, headers=auth())
            locker.rollback()
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "MATCHING_UNAVAILABLE"
    assert "statement" not in error["message"].lower()  # no database details leak out
