"""Minimal WSGI JSON API in front of the employer handler.

Routes (all POST):
    /api/employer/register              public registration
    /api/employer/verify-email          public email verification
    /api/employer/<action>              authenticated action from ACTIONS

The API is framework-free so it can be mounted under any WSGI server or kept
behind an existing gateway.  Business errors are returned with their category
and mapped to HTTP status codes.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .constants import CATEGORY_HTTP_STATUS, MAX_REQUEST_BYTES
from .context import AppContext
from .handler import handle, handle_public

logger = logging.getLogger(__name__)

PUBLIC_ROUTES = {
    "/api/employer/register": "register",
    "/api/employer/verify-email": "verify_email",
}
ACTION_PREFIX = "/api/employer/"

SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("Cache-Control", "no-store"),
)


def to_jsonable(value: Any) -> Any:
    """Recursively convert common Python values into JSON-safe values."""

    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, bool) or value is None or isinstance(value, (int, float, str)):
        return value
    return str(value)


class EmployerAPI:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    def __call__(self, environ, start_response):
        try:
            return self._dispatch(environ, start_response)
        except Exception:  # defensive: never leak a traceback to a caller
            logger.exception("Unhandled WSGI error")
            return self._json(
                start_response,
                500,
                {
                    "ok": False,
                    "category": "server",
                    "message": "Something went wrong.",
                    "fields": {},
                },
            )

    def _dispatch(self, environ, start_response):
        method = environ.get("REQUEST_METHOD", "").upper()
        if method != "POST":
            return self._json(
                start_response,
                405,
                {
                    "ok": False,
                    "category": "invalid",
                    "message": "POST required.",
                    "fields": {},
                },
                extra_headers=(("Allow", "POST"),),
            )

        path = environ.get("PATH_INFO", "").rstrip("/") or "/"
        payload, error_response = self._read_payload(environ)
        if error_response is not None:
            return error_response(start_response)

        if path in PUBLIC_ROUTES:
            result = handle_public(self.ctx, PUBLIC_ROUTES[path], payload)
        elif path.startswith(ACTION_PREFIX) and "/" not in path[len(ACTION_PREFIX):]:
            action = path[len(ACTION_PREFIX):]
            if not action:
                return self._not_found(start_response)
            token = self._bearer_token(environ)
            result = handle(self.ctx, token, action, payload)
        else:
            return self._not_found(start_response)

        if not result.get("ok"):
            status = CATEGORY_HTTP_STATUS.get(result.get("category"), 500)
            return self._json(start_response, status, result)

        data = result.get("data")
        if isinstance(data, (bytes, bytearray)):
            body = bytes(data)
            start_response(
                "200 OK",
                [
                    ("Content-Type", "application/octet-stream"),
                    ("Content-Length", str(len(body))),
                    ("Content-Disposition", 'attachment; filename="applicant-cv"'),
                    *SECURITY_HEADERS,
                ],
            )
            return [body]
        return self._json(start_response, 200, result)

    def _read_payload(self, environ):
        raw_length = environ.get("CONTENT_LENGTH") or "0"
        try:
            length = int(raw_length)
        except (TypeError, ValueError):
            length = 0
        if length < 0:
            length = 0
        if length > MAX_REQUEST_BYTES:
            return None, lambda start: self._json(
                start,
                413,
                {
                    "ok": False,
                    "category": "invalid",
                    "message": "Request body is too large.",
                    "fields": {},
                },
            )

        raw = environ["wsgi.input"].read(length) if length else b""
        if not raw:
            return {}, None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, lambda start: self._json(
                start,
                400,
                {
                    "ok": False,
                    "category": "invalid",
                    "message": "The request body must be valid JSON.",
                    "fields": {},
                },
            )
        if not isinstance(payload, dict):
            return None, lambda start: self._json(
                start,
                400,
                {
                    "ok": False,
                    "category": "invalid",
                    "message": "The request payload must be an object.",
                    "fields": {},
                },
            )
        return payload, None

    @staticmethod
    def _bearer_token(environ) -> str | None:
        header = environ.get("HTTP_AUTHORIZATION", "")
        if not isinstance(header, str):
            return None
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return None
        return token.strip()

    def _not_found(self, start_response):
        return self._json(
            start_response,
            404,
            {
                "ok": False,
                "category": "not_found",
                "message": "Endpoint not found.",
                "fields": {},
            },
        )

    @staticmethod
    def _json(start_response, status: int, payload: dict, extra_headers=()):
        body = json.dumps(
            to_jsonable(payload), ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        reason = {
            200: "OK",
            400: "Bad Request",
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not Found",
            405: "Method Not Allowed",
            409: "Conflict",
            413: "Payload Too Large",
            500: "Internal Server Error",
        }.get(status, "Error")
        headers = [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            *SECURITY_HEADERS,
            *extra_headers,
        ]
        start_response(f"{status} {reason}", headers)
        return [body]
