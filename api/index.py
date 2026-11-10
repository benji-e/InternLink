"""Shared Vercel entry point for InternLink's matching and employer APIs."""

from __future__ import annotations

import json
import logging
import os
import secrets
import sys
import threading
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from html import escape
from http.server import BaseHTTPRequestHandler
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request as URLRequest, urlopen

import jwt
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from employer_module.internlink_employer.adapters import LocalFileStorage, MemoryNotifier
from employer_module.internlink_employer.api import EmployerAPI
from employer_module.internlink_employer.constants import MAX_REQUEST_BYTES
from employer_module.internlink_employer.context import AppContext
from employer_module.internlink_employer.db import PostgresDatabase
from employer_module.internlink_employer.security import ReferenceTokenService
from matching_engine.config import DEFAULT_CONFIG
from matching_engine.service import (
    MatchingUnavailable,
    ProfileIncomplete,
    recommend_for_student,
    student_id_for_user,
)
from student_module import accounts as account_service
from student_module import catalog as catalog_service
from student_module import messages as message_service
from student_module import public as public_service
from student_module import admin as admin_service
from student_module import alerts as alert_service
from student_module import cv as cv_service
from student_module import invites as invite_service
from student_module import saved as saved_service
from student_module import service as student_service

logger = logging.getLogger("internlink.vercel")
RECOMMENDATIONS_PATH = "/api/v1/students/me/recommendations"
HEALTH_PATH = "/api/health"
EMPLOYER_PREFIX = "/api/employer/"
MODULE_ROOT = Path(__file__).resolve().parents[1]

_matching_pool: ConnectionPool | None = None
_matching_pool_lock = threading.Lock()


class ConfigurationError(RuntimeError):
    """Raised when an API's required Vercel environment is incomplete."""


class ResendMailer:
    """Deliver employer verification messages through the configured Resend account."""

    def send(self, recipient: str, subject: str, body: str) -> None:
        api_key = os.environ.get("RESEND_API_KEY")
        from_email = os.environ.get("INTERNLINK_FROM_EMAIL")
        if not api_key or not from_email:
            raise ConfigurationError("Email requires RESEND_API_KEY and INTERNLINK_FROM_EMAIL.")
        data = json.dumps(
            {
                "from": from_email,
                "to": [recipient],
                "subject": subject,
                "html": f'<p>Welcome to InternLink.</p><p><a href="{escape(body)}">Verify your email address</a></p>',
            }
        ).encode("utf-8")
        request = URLRequest(
            "https://api.resend.com/emails",
            data=data,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=8) as response:
                if response.status >= 300:
                    raise RuntimeError(f"Email provider returned HTTP {response.status}")
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as exc:
            logger.exception("Could not send employer email verification")
            raise ConfigurationError("Could not send the verification email. Please try again later.") from exc


def _json_bytes(payload: dict) -> bytes:
    def serialize(value):
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

    return json.dumps(payload, default=serialize).encode("utf-8")


def _get_matching_pool() -> ConnectionPool:
    global _matching_pool

    dsn = os.environ.get("INTERNLINK_DSN")
    if not dsn:
        raise ConfigurationError("INTERNLINK_DSN is not configured")
    if _matching_pool is not None:
        return _matching_pool

    with _matching_pool_lock:
        if _matching_pool is None:
            pool = ConnectionPool(
                dsn,
                min_size=1,
                max_size=min(DEFAULT_CONFIG.pool_size, 4),
                kwargs={"autocommit": True},
                open=False,
            )
            try:
                pool.open(wait=True, timeout=5)
            except Exception:
                pool.close()
                raise
            _matching_pool = pool
    return _matching_pool


def _build_employer_context() -> tuple[AppContext, PostgresDatabase]:
    secret = os.environ.get("INTERNLINK_JWT_SECRET", "")
    if len(secret) < 32:
        raise ConfigurationError("INTERNLINK_JWT_SECRET must contain at least 32 characters.")

    db = PostgresDatabase(_get_matching_pool())
    cv_root = Path(os.environ.get("INTERNLINK_CV_ROOT", MODULE_ROOT / "employer_module" / "data" / "cvs"))
    base_url = os.environ.get("INTERNLINK_PUBLIC_BASE_URL")
    if not base_url:
        deployment_url = os.environ.get("VERCEL_URL")
        base_url = f"https://{deployment_url}" if deployment_url else "http://localhost"

    context = AppContext(
        db=db,
        auth=ReferenceTokenService(secret),
        mailer=ResendMailer(),
        notifier=MemoryNotifier(),
        storage=cv_service.DatabaseCvStorage(_get_matching_pool(), fallback=LocalFileStorage(cv_root)),
        base_url=base_url,
    )
    return context, db


class handler(BaseHTTPRequestHandler):
    """Vercel's Python HTTP handler, dispatching both backend APIs."""

    def do_GET(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch()

    def do_PUT(self):
        self._dispatch()

    def do_PATCH(self):
        self._dispatch()

    def do_DELETE(self):
        self._dispatch()

    def do_OPTIONS(self):
        self._dispatch()

    def _dispatch(self):
        path = urlsplit(self.path).path.rstrip("/") or "/"
        if path in ("/", HEALTH_PATH) and self.command == "GET":
            self._send_json(200, {"service": "InternLink API", "status": "ok"})
            return
        if path == RECOMMENDATIONS_PATH:
            if self.command != "GET":
                self._send_json(405, {"detail": "Method Not Allowed"}, (("Allow", "GET"),))
                return
            self._recommendations()
            return
        if path.startswith("/api/v1/"):
            self._student_api(path)
            return
        if path == "/api/cron/job-alerts":
            self._cron_job_alerts()
            return
        if path.startswith(EMPLOYER_PREFIX):
            if self.command != "POST":
                self._send_json(405, {"detail": "Method Not Allowed"}, (("Allow", "POST"),))
                return
            self._employer_request(path)
            return
        self._send_json(404, {"detail": "Not Found"})

    def _student_api(self, path: str):
        routes = {
            "/api/v1/auth/register": ("POST", self._student_register),
            "/api/v1/auth/login": ("POST", self._student_login),
            "/api/v1/auth/verify-email": ("POST", self._student_verify_email),
            "/api/v1/auth/register-university": ("POST", self._university_register),
            "/api/v1/auth/resend-verification": ("POST", self._resend_verification),
            "/api/v1/auth/forgot-password": ("POST", self._forgot_password),
            "/api/v1/auth/reset-password": ("POST", self._reset_password),
            "/api/v1/admin/registrations": ("GET", self._admin_registrations),
            "/api/v1/admin/users": ("GET", self._admin_users),
            "/api/v1/admin/audit": ("GET", self._admin_audit),
            "/api/v1/coordinator/dashboard": ("GET", self._coordinator_dashboard),
            "/api/v1/coordinator/students": ("GET", self._coordinator_students),
            "/api/v1/coordinator/placements": ("GET", self._coordinator_placements),
            "/api/v1/coordinator/catalog": ("GET", self._coordinator_catalog),
            "/api/v1/coordinator/departments": ("POST", self._coordinator_add_department),
            "/api/v1/coordinator/programmes": ("POST", self._coordinator_add_programme),
            "/api/v1/public/universities": ("GET", self._student_universities),
            "/api/v1/public/catalogs": ("GET", self._student_catalogs),
            "/api/v1/public/home": ("GET", self._public_home),
            "/api/v1/public/opportunities": ("GET", self._public_opportunities),
            "/api/v1/public/university-requests": ("POST", self._public_university_request),
            "/api/v1/students/me/profile": ("GET, PUT", self._student_profile),
            "/api/v1/opportunities": ("GET", self._student_opportunities),
            "/api/v1/students/me/applications": ("GET, POST", self._student_applications),
            "/api/v1/students/me/notifications": ("GET", self._student_notifications),
            "/api/v1/students/me/saved": ("GET", self._student_saved_list),
            "/api/v1/admin/university-requests": ("GET, POST", self._admin_university_requests),
            "/api/v1/students/me/cv": ("GET, PUT, DELETE", self._student_cv),
            "/api/v1/students/me/cv/file": ("GET", self._student_cv_file),
            "/api/v1/students/me/alerts": ("GET, POST", self._student_alerts),
            "/api/v1/admin/universities": ("GET", self._admin_universities),
            "/api/v1/coordinator/coordinators": ("GET, POST", self._coordinator_coordinators),
            "/api/v1/auth/invite": ("GET", self._invite_details),
            "/api/v1/auth/accept-invite": ("POST", self._accept_invite),
        }
        route = routes.get(path)
        if route:
            allowed, callback = route
            if self.command not in allowed.split(", "):
                self._send_json(405, {"detail": "Method Not Allowed"}, (("Allow", allowed),))
                return
            callback()
            return

        parts = path.strip("/").split("/")
        if len(parts) == 6 and parts[:5] == ["api", "v1", "students", "me", "alerts"] and parts[5].isdigit():
            if self.command != "DELETE":
                self._send_json(405, {"detail": "Method Not Allowed"}, (("Allow", "DELETE"),))
                return
            self._student_alert_delete(int(parts[5]))
            return
        if len(parts) == 6 and parts[:4] == ["api", "v1", "admin", "universities"] and parts[4].isdigit() and parts[5] == "coordinators":
            if self.command not in ("GET", "POST"):
                self._send_json(405, {"detail": "Method Not Allowed"}, (("Allow", "GET, POST"),))
                return
            self._admin_university_coordinators(int(parts[4]))
            return
        if len(parts) == 6 and parts[:3] == ["api", "v1", "public"] and parts[3] == "universities" and parts[5] == "departments":
            self._student_catalog_detail(parts[4], "departments")
            return
        if len(parts) == 6 and parts[:4] == ["api", "v1", "public", "universities"] and parts[5] == "programmes":
            self._public_university_programmes(parts[4])
            return
        if len(parts) == 5 and parts[:4] == ["api", "v1", "public", "opportunities"]:
            self._public_opportunity_detail(parts[4])
            return
        if (
            len(parts) == 7
            and parts[:5] == ["api", "v1", "students", "me", "applications"]
            and parts[6] == "messages"
            and parts[5].isdigit()
        ):
            if self.command not in ("GET", "POST"):
                self._send_json(405, {"detail": "Method Not Allowed"}, (("Allow", "GET, POST"),))
                return
            self._student_messages(int(parts[5]))
            return
        if len(parts) == 6 and parts[:3] == ["api", "v1", "public"] and parts[3] == "departments" and parts[5] == "programmes":
            self._student_catalog_detail(parts[4], "programmes")
            return
        if (
            len(parts) == 7
            and parts[:5] == ["api", "v1", "students", "me", "applications"]
            and parts[6] == "withdraw"
            and parts[5].isdigit()
        ):
            if self.command != "POST":
                self._send_json(405, {"detail": "Method Not Allowed"}, (("Allow", "POST"),))
                return
            self._student_withdraw_application(int(parts[5]))
            return
        if (
            len(parts) == 7
            and parts[:5] == ["api", "v1", "students", "me", "notifications"]
            and parts[5].isdigit()
            and parts[6] == "read"
        ):
            if self.command != "POST":
                self._send_json(405, {"detail": "Method Not Allowed"}, (("Allow", "POST"),))
                return
            self._student_mark_notification_read(int(parts[5]))
            return
        if len(parts) == 6 and parts[:4] == ["api", "v1", "admin", "registrations"] and parts[5].isdigit():
            if self.command == "GET":
                self._admin_registration_detail(parts[4], int(parts[5]))
                return
            if self.command != "POST":
                self._send_json(405, {"detail": "Method Not Allowed"}, (("Allow", "GET, POST"),))
                return
            self._admin_decide_registration(parts[4], int(parts[5]))
            return
        if len(parts) == 6 and parts[:5] == ["api", "v1", "students", "me", "saved"] and parts[5].isdigit():
            if self.command not in ("PUT", "DELETE"):
                self._send_json(405, {"detail": "Method Not Allowed"}, (("Allow", "PUT, DELETE"),))
                return
            self._student_saved_change(int(parts[5]))
            return
        if len(parts) == 5 and parts[:4] == ["api", "v1", "admin", "users"] and parts[4].isdigit():
            if self.command != "PATCH":
                self._send_json(405, {"detail": "Method Not Allowed"}, (("Allow", "PATCH"),))
                return
            self._admin_update_user(int(parts[4]))
            return
        if len(parts) == 5 and parts[:4] == ["api", "v1", "coordinator", "students"] and parts[4].isdigit():
            if self.command != "POST" or parts[4] == "0":
                self._send_json(405, {"detail": "Method Not Allowed"}, (("Allow", "POST"),))
                return
            self._coordinator_verify_student(int(parts[4]))
            return
        if len(parts) == 5 and parts[:4] == ["api", "v1", "coordinator", "placements"] and parts[4].isdigit():
            if self.command != "POST":
                self._send_json(405, {"detail": "Method Not Allowed"}, (("Allow", "POST"),))
                return
            self._coordinator_decide_placement(int(parts[4]))
            return
        self._send_json(404, {"detail": "Not Found"})

    def _student_connection(self):
        return _get_matching_pool().connection()

    def _read_json_request(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            raise student_service.StudentError(400, "INVALID_CONTENT_LENGTH", "Invalid request length.") from None
        if length < 0:
            raise student_service.StudentError(400, "INVALID_CONTENT_LENGTH", "Invalid request length.")
        if length > MAX_REQUEST_BYTES:
            raise student_service.StudentError(413, "REQUEST_TOO_LARGE", "Request body is too large.")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise student_service.StudentError(400, "INVALID_JSON", "The request body must be valid JSON.") from None
        if not isinstance(payload, dict):
            raise student_service.StudentError(400, "INVALID_JSON", "The request body must be a JSON object.")
        return payload

    def _student_user_id(self) -> int:
        authorization = self.headers.get("Authorization", "")
        scheme, separator, credentials = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator or not credentials:
            raise student_service.StudentError(401, "UNAUTHENTICATED", "Sign in to continue.")
        secret = os.environ.get("INTERNLINK_JWT_SECRET")
        if not secret:
            raise ConfigurationError("INTERNLINK_JWT_SECRET is not configured")
        try:
            claims = jwt.decode(
                credentials,
                secret,
                algorithms=["HS256"],
                options={"require": ["exp", "sub", "role"]},
            )
        except jwt.PyJWTError:
            raise student_service.StudentError(401, "UNAUTHENTICATED", "Your session has expired. Sign in again.") from None
        if claims.get("role") != "student":
            raise student_service.StudentError(403, "STUDENT_ACCOUNT_REQUIRED", "A student account is required.")
        try:
            return int(claims["sub"])
        except (TypeError, ValueError, OverflowError):
            raise student_service.StudentError(401, "UNAUTHENTICATED", "Your session is invalid. Sign in again.") from None

    def _student_call(self, callback, *, success_status: int = 200, authenticated: bool = False):
        result = self._student_run(callback, authenticated=authenticated)
        if result is not None:
            self._send_json(success_status, result)

    def _student_run(self, callback, *, authenticated: bool = False):
        """Run callback(conn, user_id) and return its result.

        On failure the error response is sent here and None is returned.
        """

        try:
            user_id = self._student_user_id() if authenticated else None
            with self._student_connection() as conn:
                return callback(conn, user_id)
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
        except ConfigurationError as exc:
            self._send_json(503, {"error": {"code": "CONFIGURATION_ERROR", "message": str(exc)}})
        except psycopg.Error as exc:
            if exc.sqlstate == "23505":
                self._send_json(409, {"error": {"code": "ALREADY_EXISTS", "message": "An account or record with those details already exists."}})
                return None
            logger.exception("Student API database request failed")
            self._send_json(503, {"error": {"code": "SERVICE_UNAVAILABLE", "message": "The student service is temporarily unavailable."}})
        except (TimeoutError, OSError):
            logger.exception("Student API dependency request failed")
            self._send_json(503, {"error": {"code": "SERVICE_UNAVAILABLE", "message": "The student service is temporarily unavailable."}})
        return None

    def _student_register(self):
        try:
            payload = self._read_json_request()

            def register(conn, _user_id):
                token = secrets.token_urlsafe(32)
                with conn.transaction():
                    account = student_service.register_student(conn, payload, token)
                    self._send_verification_email(
                        payload["email"].strip().lower(),
                        payload.get("full_name", "").strip(),
                        self._verification_url("student", token),
                    )
                return {
                    "message": "Account created. Check your university email to verify it.",
                    "account_status": "pending_email_verification",
                    **account,
                }

            self._student_call(register, success_status=201)
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})

    def _university_register(self):
        try:
            payload = self._read_json_request()
            self._require_email_configuration()

            def register(conn, _user_id):
                token = secrets.token_urlsafe(32)
                with conn.transaction():
                    account = account_service.register_university(conn, payload, token)
                    self._send_verification_email(
                        account["email"], account["full_name"], self._verification_url("coordinator", token)
                    )
                return {
                    "message": (
                        "Check your email to confirm your address. Your coordinator account becomes "
                        "active once an administrator verifies your university."
                    ),
                    "account_status": "pending_email_verification",
                    "university_id": account["university_id"],
                    "user_id": account["user_id"],
                }

            self._student_call(register, success_status=201)
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
        except ConfigurationError as exc:
            self._send_json(503, {"error": {"code": "CONFIGURATION_ERROR", "message": str(exc)}})

    def _resend_verification(self):
        """Always answers the same way so the endpoint can't reveal which emails exist."""

        def issue(conn, payload, raw_token):
            return account_service.create_email_verification(conn, payload.get("email"), raw_token)

        def send(recipient, raw_token):
            self._send_verification_email(
                recipient["email"], recipient["full_name"], self._verification_url(recipient["role"], raw_token)
            )

        self._send_account_link(issue, send)

    def _forgot_password(self):
        """Always answers the same way so the endpoint can't reveal which emails exist."""

        def issue(conn, payload, raw_token):
            return account_service.create_password_reset(conn, payload.get("email"), raw_token)

        def send(recipient, raw_token):
            url = f"{self._site_url()}/reset-password?token={quote(raw_token)}"
            self._send_email(
                recipient["email"],
                "Reset your InternLink password",
                f"<p>Hello {escape(recipient['full_name'])},</p>"
                f"<p>Someone asked to reset the password for your InternLink account.</p>"
                f"<p><a href=\"{escape(url)}\">Choose a new password</a></p>"
                f"<p>This link expires in {account_service.RESET_MINUTES} minutes. "
                "If you didn't ask for this, you can ignore this email.</p>",
            )

        self._send_account_link(issue, send)

    def _send_account_link(self, issue, send):
        try:
            payload = self._read_json_request()
            self._require_email_configuration()
            raw_token = secrets.token_urlsafe(32)

            def run(conn, _user_id):
                with conn.transaction():
                    return {"recipient": issue(conn, payload, raw_token)}

            result = self._student_run(run)
            if result is None:
                return  # error already sent
            recipient = result["recipient"]
            if recipient is not None:
                try:
                    send(recipient, raw_token)
                except ConfigurationError:
                    # Already logged; answering differently would reveal the account exists.
                    pass
            self._send_json(202, {"message": account_service.GENERIC_EMAIL_MESSAGE})
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
        except ConfigurationError as exc:
            self._send_json(503, {"error": {"code": "CONFIGURATION_ERROR", "message": str(exc)}})

    def _reset_password(self):
        try:
            payload = self._read_json_request()

            def reset(conn, _user_id):
                with conn.transaction():
                    result = account_service.reset_password(conn, payload.get("token"), payload.get("password"))
                message = "Your password has been changed. You can now sign in."
                if result["awaiting_verification"]:
                    message = "Your password has been changed. Confirm your email before signing in."
                return {"message": message, **result}

            self._student_call(reset)
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})

    @staticmethod
    def _site_url() -> str:
        site_url = os.environ.get("INTERNLINK_PUBLIC_BASE_URL")
        if not site_url:
            deployment_url = os.environ.get("VERCEL_URL")
            site_url = f"https://{deployment_url}" if deployment_url else "http://localhost:5173"
        return site_url.rstrip("/")

    @classmethod
    def _verification_url(cls, role: str, raw_token: str) -> str:
        # Employer links are checked by the employer module at /verify-email.
        path = "verify-email" if role == "employer" else "verify"
        return f"{cls._site_url()}/{path}?token={quote(raw_token)}"

    @staticmethod
    def _require_email_configuration():
        if not os.environ.get("RESEND_API_KEY") or not os.environ.get("INTERNLINK_FROM_EMAIL"):
            raise ConfigurationError("Sending email requires RESEND_API_KEY and INTERNLINK_FROM_EMAIL.")

    @classmethod
    def _send_verification_email(cls, email: str, name: str, verification_url: str):
        cls._send_email(
            email,
            "Confirm your InternLink email address",
            f"<p>Hello {escape(name)},</p><p>Confirm your email address to activate your "
            f"InternLink account:</p><p><a href=\"{escape(verification_url)}\">Confirm email</a></p>"
            "<p>This link expires in 24 hours. If you did not create this account, ignore this email.</p>",
        )

    @classmethod
    def _send_email(cls, email: str, subject: str, html: str):
        cls._require_email_configuration()
        data = json.dumps(
            {
                "from": os.environ["INTERNLINK_FROM_EMAIL"],
                "to": [email],
                "subject": subject,
                "html": html,
            }
        ).encode("utf-8")
        api_key = os.environ["RESEND_API_KEY"]
        request = URLRequest(
            "https://api.resend.com/emails",
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=8) as response:
                if response.status >= 300:
                    raise RuntimeError(f"Email provider returned HTTP {response.status}")
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as exc:
            logger.exception("Could not send an account email")
            raise ConfigurationError("Could not send the email. Please try again later.") from exc

    def _student_login(self):
        try:
            payload = self._read_json_request()
            secret = os.environ.get("INTERNLINK_JWT_SECRET")
            if not secret:
                raise ConfigurationError("INTERNLINK_JWT_SECRET is not configured")

            def login(conn, _user_id):
                account = student_service.authenticate_user(
                    conn, payload.get("email", ""), payload.get("password", "")
                )
                expires = datetime.now(timezone.utc) + timedelta(hours=8)
                access_token = jwt.encode(
                    {"sub": str(account["user_id"]), "role": account["role"], "exp": expires},
                    secret,
                    algorithm="HS256",
                )
                return {
                    "access_token": access_token,
                    "token_type": "Bearer",
                    "user": {
                        **account,
                        "role": "university" if account["role"] == "coordinator" else account["role"],
                    },
                }

            self._student_call(login)
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
        except ConfigurationError as exc:
            self._send_json(503, {"error": {"code": "CONFIGURATION_ERROR", "message": str(exc)}})

    def _authorized_user_id(self, allowed_roles: set[str]) -> tuple[int, str]:
        authorization = self.headers.get("Authorization", "")
        scheme, separator, credentials = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator or not credentials:
            raise student_service.StudentError(401, "UNAUTHENTICATED", "Sign in to continue.")
        secret = os.environ.get("INTERNLINK_JWT_SECRET")
        if not secret:
            raise ConfigurationError("INTERNLINK_JWT_SECRET is not configured")
        try:
            claims = jwt.decode(
                credentials,
                secret,
                algorithms=["HS256"],
                options={"require": ["exp", "sub", "role"]},
            )
            user_id = int(claims["sub"])
            role = str(claims["role"])
        except (jwt.PyJWTError, TypeError, ValueError, KeyError, OverflowError):
            raise student_service.StudentError(401, "UNAUTHENTICATED", "Your session has expired. Sign in again.") from None
        if role not in allowed_roles:
            raise student_service.StudentError(403, "ROLE_REQUIRED", "Your account does not have permission for this action.")
        return user_id, role

    def _role_call(self, callback, allowed_roles: set[str]):
        result = self._role_run(callback, allowed_roles)
        if result is not None:
            self._send_json(200, result)

    def _role_run(self, callback, allowed_roles: set[str]):
        """Run callback(conn, user_id) for a signed-in, active user of an allowed role.

        Returns the result, or sends the error response and returns None.
        """
        try:
            user_id, role = self._authorized_user_id(allowed_roles)
            with self._student_connection() as conn:
                # Role handlers read columns by name; pooled connections return
                # tuples by default, so switch for this request only.
                default_row_factory = conn.row_factory
                conn.row_factory = dict_row
                try:
                    account = conn.execute(
                        "SELECT role, status FROM users WHERE user_id = %s",
                        (user_id,),
                    ).fetchone()
                    if account is None or account["role"] != role or account["status"] != "active":
                        raise student_service.StudentError(403, "ACCOUNT_NOT_ACTIVE", "Your account is not active.")
                    return callback(conn, user_id)
                finally:
                    conn.row_factory = default_row_factory
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
        except ConfigurationError as exc:
            self._send_json(503, {"error": {"code": "CONFIGURATION_ERROR", "message": str(exc)}})
        except psycopg.Error:
            logger.exception("Role API database request failed")
            self._send_json(503, {"error": {"code": "SERVICE_UNAVAILABLE", "message": "The service is temporarily unavailable."}})
        return None

    def _admin_registrations(self):
        self._role_call(
            lambda conn, _user_id: {
                "registrations": conn.execute(
                    "SELECT org_type, org_id, name, contact, submitted_at FROM v_admin_pending_registrations ORDER BY submitted_at"
                ).fetchall()
            },
            {"admin"},
        )

    def _admin_registration_detail(self, org_type: str, org_id: int):
        self._role_call(lambda conn, _user_id: {"registration": admin_service.registration_detail(conn, org_type, org_id)}, {"admin"})

    def _admin_university_requests(self):
        try:
            payload = self._read_json_request() if self.command == "POST" else {}
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
            return

        def run(conn, user_id):
            if self.command == "GET":
                return {"requests": admin_service.university_requests(conn)}
            with conn.transaction():
                conn.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))
                return admin_service.close_university_request(conn, payload)
        self._role_call(run, {"admin"})

    def _admin_users(self):
        self._role_call(
            lambda conn, _user_id: {
                "users": conn.execute(
                    """
                    SELECT u.user_id, u.email, u.full_name, u.role, u.status, u.created_at,
                           coalesce(c.name, un.name) AS organisation
                    FROM users u
                    LEFT JOIN companies c ON c.company_id = u.company_id
                    LEFT JOIN universities un ON un.university_id = u.university_id
                    ORDER BY u.created_at DESC, u.user_id DESC
                    LIMIT 200
                    """
                ).fetchall()
            },
            {"admin"},
        )

    def _admin_audit(self):
        self._role_call(
            lambda conn, _user_id: {
                "events": conn.execute(
                    """
                    SELECT al.log_id, al.action, al.resource_type, al.resource_id, al.result,
                           al.occurred_at, u.full_name AS actor_name
                    FROM audit_logs al LEFT JOIN users u ON u.user_id = al.actor_user_id
                    ORDER BY al.occurred_at DESC, al.log_id DESC LIMIT 100
                    """
                ).fetchall()
            },
            {"admin"},
        )

    def _admin_decide_registration(self, org_type: str, org_id: int):
        try:
            payload = self._read_json_request()
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
            return
        action = payload.get("action")
        if action not in {"verified", "rejected"}:
            self._send_json(422, {"error": {"code": "INVALID_ACTION", "message": "Choose verified or rejected."}})
            return
        reason = payload.get("reason", "")
        if action == "rejected" and (not isinstance(reason, str) or not reason.strip()):
            self._send_json(422, {"error": {"code": "REJECTION_REASON_REQUIRED", "message": "Provide a reason for rejection."}})
            return
        table, id_column, status_column = {
            "company": ("companies", "company_id", "verification_status"),
            "university": ("universities", "university_id", "status"),
        }.get(org_type, (None, None, None))
        if not table:
            self._send_json(404, {"detail": "Registration not found."})
            return

        def decide(conn, user_id):
            state = "verified" if action == "verified" else "rejected"
            with conn.transaction():
                conn.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))
                cursor = conn.execute(
                    f"UPDATE {table} SET {status_column} = %s, rejection_reason = %s WHERE {id_column} = %s AND {status_column} = 'pending'",
                    (state, None if state == "verified" else reason.strip(), org_id),
                )
                if cursor.rowcount != 1:
                    raise student_service.StudentError(404, "REGISTRATION_NOT_FOUND", "That registration is no longer pending.")
                if org_type == "university" and state == "verified":
                    account_service.activate_university_coordinators(conn, org_id)
            return {"status": state}

        self._role_call(decide, {"admin"})

    def _admin_update_user(self, target_user_id: int):
        try:
            payload = self._read_json_request()
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
            return
        status = payload.get("status")
        if status not in {"active", "suspended", "rejected"}:
            self._send_json(422, {"error": {"code": "INVALID_STATUS", "message": "Choose active, suspended or rejected."}})
            return

        def update(conn, actor_id):
            with conn.transaction():
                conn.execute("SELECT set_config('app.user_id', %s, true)", (str(actor_id),))
                cursor = conn.execute(
                    "UPDATE users SET status = %s WHERE user_id = %s AND role <> 'admin' AND (status <> 'active' OR email_verified_at IS NOT NULL)",
                    (status, target_user_id),
                )
                if cursor.rowcount != 1:
                    raise student_service.StudentError(404, "USER_NOT_FOUND", "User not found or cannot be activated before email verification.")
            return {"user_id": target_user_id, "status": status}

        self._role_call(update, {"admin"})

    def _coordinator_scope(self, conn, user_id: int) -> dict:
        scope = conn.execute(
            "SELECT university_id, department_id FROM users WHERE user_id = %s AND role = 'coordinator' AND status = 'active'",
            (user_id,),
        ).fetchone()
        if scope is None:
            raise student_service.StudentError(403, "COORDINATOR_REQUIRED", "An active university coordinator account is required.")
        return scope

    def _coordinator_dashboard(self):
        def dashboard(conn, user_id):
            scope = self._coordinator_scope(conn, user_id)
            stats = conn.execute(
                """
                SELECT coalesce(sum(enrolled), 0) AS enrolled,
                       coalesce(sum(placed), 0) AS placed,
                       coalesce(sum(pending), 0) AS pending,
                       coalesce(sum(unplaced), 0) AS unplaced
                FROM v_department_placement_stats
                WHERE university_id = %s AND (%s::bigint IS NULL OR department_id = %s)
                """,
                (scope["university_id"], scope["department_id"], scope["department_id"]),
            ).fetchone()
            return {"stats": stats}
        self._role_call(dashboard, {"coordinator"})

    def _coordinator_students(self):
        def students(conn, user_id):
            scope = self._coordinator_scope(conn, user_id)
            rows = conn.execute(
                """
                SELECT sp.student_id, u.full_name, u.email, sp.student_number, p.name AS programme,
                       sp.year_of_study, sp.verified,
                       coalesce(ps.placement_state, 'unplaced') AS placement_status,
                       sp.created_at AS registered_at,
                       (SELECT count(*) FROM applications ap WHERE ap.student_id = sp.student_id) AS applications_count
                FROM student_profiles sp
                JOIN users u ON u.user_id = sp.user_id
                JOIN programmes p ON p.programme_id = sp.programme_id
                LEFT JOIN v_student_placement_state ps ON ps.student_id = sp.student_id
                WHERE sp.university_id = %s AND (%s::bigint IS NULL OR sp.department_id = %s)
                ORDER BY u.full_name
                """,
                (scope["university_id"], scope["department_id"], scope["department_id"]),
            ).fetchall()
            return {"students": rows}
        self._role_call(students, {"coordinator"})

    def _coordinator_placements(self):
        def placements(conn, user_id):
            scope = self._coordinator_scope(conn, user_id)
            rows = conn.execute(
                """
                SELECT v.placement_id, v.queued_at, v.student_id, v.student_name, v.student_number,
                       v.programme, v.company_name, v.listing_title, v.application_id,
                       l.location, l.is_remote, l.duration_weeks
                FROM v_pending_placements v
                JOIN applications a ON a.application_id = v.application_id
                JOIN listings l ON l.listing_id = a.listing_id
                WHERE v.university_id = %s AND (%s::bigint IS NULL OR v.department_id = %s)
                ORDER BY v.queued_at
                """,
                (scope["university_id"], scope["department_id"], scope["department_id"]),
            ).fetchall()
            return {"placements": rows}
        self._role_call(placements, {"coordinator"})

    def _coordinator_catalog(self):
        def catalog(conn, user_id):
            scope = self._coordinator_scope(conn, user_id)
            return catalog_service.list_catalog(conn, scope["university_id"], scope["department_id"])
        self._role_call(catalog, {"coordinator"})

    def _coordinator_add_department(self):
        self._coordinator_catalog_write(catalog_service.add_department)

    def _coordinator_add_programme(self):
        self._coordinator_catalog_write(catalog_service.add_programme)

    def _coordinator_catalog_write(self, method):
        try:
            payload = self._read_json_request()
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
            return

        def write(conn, user_id):
            scope = self._coordinator_scope(conn, user_id)
            with conn.transaction():
                conn.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))
                return method(conn, scope["university_id"], scope["department_id"], payload)
        self._role_call(write, {"coordinator"})

    def _coordinator_verify_student(self, student_id: int):
        def verify(conn, user_id):
            scope = self._coordinator_scope(conn, user_id)
            with conn.transaction():
                conn.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))
                cursor = conn.execute(
                    """
                    UPDATE student_profiles SET verified = true
                    WHERE student_id = %s AND university_id = %s
                      AND (%s::bigint IS NULL OR department_id = %s)
                    """,
                    (student_id, scope["university_id"], scope["department_id"], scope["department_id"]),
                )
                if cursor.rowcount != 1:
                    raise student_service.StudentError(404, "STUDENT_NOT_FOUND", "Student not found in your university scope.")
            return {"student_id": student_id, "verified": True}
        self._role_call(verify, {"coordinator"})

    def _coordinator_decide_placement(self, placement_id: int):
        try:
            payload = self._read_json_request()
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
            return
        action = payload.get("action")
        if action not in {"confirmed", "rejected"}:
            self._send_json(422, {"error": {"code": "INVALID_ACTION", "message": "Choose confirmed or rejected."}})
            return
        reason = payload.get("reason", "")
        if action == "rejected" and (not isinstance(reason, str) or not reason.strip()):
            self._send_json(422, {"error": {"code": "REJECTION_REASON_REQUIRED", "message": "Provide a reason for rejection."}})
            return
        # A confirmed placement needs dates. The start defaults to today and the
        # end follows from the internship's length in weeks.
        start_date = None
        if action == "confirmed" and payload.get("start_date"):
            try:
                start_date = date.fromisoformat(str(payload["start_date"]))
            except ValueError:
                self._send_json(422, {"error": {"code": "INVALID_DATE", "message": "Choose a valid start date."}})
                return

        def decide(conn, user_id):
            scope = self._coordinator_scope(conn, user_id)
            try:
                with conn.transaction():
                    conn.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))
                    cursor = conn.execute(
                        """
                        UPDATE placements p SET status = %s, rejection_reason = %s,
                               start_date = CASE WHEN %s = 'confirmed' THEN coalesce(p.start_date, %s::date, CURRENT_DATE) ELSE p.start_date END,
                               end_date = CASE WHEN %s = 'confirmed'
                                               THEN coalesce(p.end_date, coalesce(p.start_date, %s::date, CURRENT_DATE) + l.duration_weeks * 7)
                                               ELSE p.end_date END
                        FROM applications a
                        JOIN student_profiles sp ON sp.student_id = a.student_id
                        JOIN listings l ON l.listing_id = a.listing_id
                        WHERE p.application_id = a.application_id AND p.placement_id = %s
                          AND p.status = 'pending' AND sp.university_id = %s
                          AND (%s::bigint IS NULL OR sp.department_id = %s)
                        """,
                        (action, None if action == "confirmed" else reason.strip(),
                         action, start_date, action, start_date, placement_id,
                         scope["university_id"], scope["department_id"], scope["department_id"]),
                    )
            except psycopg.errors.IntegrityConstraintViolation as exc:
                if "RULE_SR13_NO_SLOTS" in str(exc):
                    raise student_service.StudentError(409, "NO_SLOTS", "All positions for this internship are already filled.") from None
                raise
            if cursor.rowcount != 1:
                raise student_service.StudentError(404, "PLACEMENT_NOT_FOUND", "Placement not found in your university scope.")
            return {"placement_id": placement_id, "status": action}
        self._role_call(decide, {"coordinator"})

    def _student_verify_email(self):
        try:
            payload = self._read_json_request()
            token = payload.get("token")
            if not isinstance(token, str) or not token.strip():
                raise student_service.StudentError(400, "INVALID_VERIFICATION_TOKEN", "Verification token is required.")

            def verify(conn, _user_id):
                with conn.transaction():
                    return account_service.verify_account_email(conn, token.strip())

            self._student_call(verify)
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})

    def _student_universities(self):
        self._student_call(lambda conn, _user_id: {"universities": student_service.list_universities(conn)})

    def _student_catalog_detail(self, raw_id: str, kind: str):
        try:
            record_id = int(raw_id)
            if record_id <= 0:
                raise ValueError
        except ValueError:
            self._send_json(422, {"error": {"code": "INVALID_ID", "message": "Invalid catalog id."}})
            return
        method = student_service.list_departments if kind == "departments" else student_service.list_programmes
        key = kind
        self._student_call(lambda conn, _user_id: {key: method(conn, record_id)})

    def _student_catalogs(self):
        self._student_call(lambda conn, _user_id: student_service.get_catalogs(conn))

    def _student_profile(self):
        try:
            user_id = self._student_user_id()
            with self._student_connection() as conn:
                student_id = student_service.student_id_for_user(conn, user_id)
                if self.command == "GET":
                    result = student_service.get_profile(conn, student_id)
                else:
                    payload = self._read_json_request()
                    with conn.transaction():
                        conn.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))
                        result = student_service.update_profile(conn, student_id, payload)
            self._send_json(200, {"profile": result})
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
        except ConfigurationError as exc:
            self._send_json(503, {"error": {"code": "CONFIGURATION_ERROR", "message": str(exc)}})
        except psycopg.Error:
            logger.exception("Student profile request failed")
            self._send_json(503, {"error": {"code": "SERVICE_UNAVAILABLE", "message": "The student service is temporarily unavailable."}})

    def _student_opportunities(self):
        try:
            user_id = self._student_user_id()
            filters = {
                key: value[0]
                for key, value in parse_qs(urlsplit(self.path).query, keep_blank_values=True).items()
            }
            with self._student_connection() as conn:
                student_id = student_service.student_id_for_user(conn, user_id)
                result = student_service.list_opportunities(conn, student_id, filters)
            self._send_json(200, result)
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
        except ConfigurationError as exc:
            self._send_json(503, {"error": {"code": "CONFIGURATION_ERROR", "message": str(exc)}})
        except psycopg.Error:
            logger.exception("Student opportunity search failed")
            self._send_json(503, {"error": {"code": "SERVICE_UNAVAILABLE", "message": "The student service is temporarily unavailable."}})

    def _student_applications(self):
        try:
            user_id = self._student_user_id()
            with self._student_connection() as conn:
                student_id = student_service.student_id_for_user(conn, user_id)
                if self.command == "GET":
                    result = student_service.list_applications(conn, student_id)
                    unread = message_service.unread_by_application(conn, user_id)
                    for row in result:
                        row["unread_messages"] = unread.get(int(row["application_id"]), 0)
                    self._send_json(200, {"applications": result})
                    return
                payload = self._read_json_request()
                with conn.transaction():
                    result = student_service.submit_application(conn, user_id, student_id, payload)
            self._send_json(201, {"application": result})
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
        except ConfigurationError as exc:
            self._send_json(503, {"error": {"code": "CONFIGURATION_ERROR", "message": str(exc)}})
        except psycopg.Error as exc:
            if exc.sqlstate == "23505":
                self._send_json(409, {"error": {"code": "ALREADY_APPLIED", "message": "You have already applied for this opportunity."}})
                return
            logger.exception("Student application request failed")
            self._send_json(503, {"error": {"code": "SERVICE_UNAVAILABLE", "message": "The student service is temporarily unavailable."}})

    def _optional_student_id(self, conn) -> int | None:
        """The signed-in student's profile id, or None for visitors.

        Public pages show extra detail (match score, applied status) to a
        signed-in student but never fail because of a stale or foreign token.
        """
        if not self.headers.get("Authorization"):
            return None
        try:
            user_id = self._student_user_id()
            return student_service.student_id_for_user(conn, user_id)
        except (student_service.StudentError, ConfigurationError):
            return None

    def _public_home(self):
        self._student_call(lambda conn, _user_id: public_service.home(conn, self._optional_student_id(conn)))

    def _public_opportunities(self):
        query = parse_qs(urlsplit(self.path).query)
        filters = {key: values[-1] for key, values in query.items()}
        self._student_call(
            lambda conn, _user_id: public_service.search_opportunities(conn, filters, self._optional_student_id(conn))
        )

    def _public_opportunity_detail(self, raw_id: str):
        if not raw_id.isdigit() or int(raw_id) <= 0:
            self._send_json(404, {"error": {"code": "LISTING_NOT_FOUND", "message": "Internship not found."}})
            return
        listing_id = int(raw_id)
        self._student_call(
            lambda conn, _user_id: {
                "opportunity": public_service.opportunity_detail(conn, listing_id, self._optional_student_id(conn))
            }
        )

    def _public_university_programmes(self, raw_id: str):
        if not raw_id.isdigit() or int(raw_id) <= 0:
            self._send_json(422, {"error": {"code": "INVALID_ID", "message": "Invalid catalog id."}})
            return
        university_id = int(raw_id)
        self._student_call(lambda conn, _user_id: {"programmes": public_service.university_programmes(conn, university_id)})

    def _public_university_request(self):
        try:
            payload = self._read_json_request()
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
            return

        def save(conn, _user_id):
            with conn.transaction():
                return public_service.request_university(conn, payload)
        self._student_call(save, success_status=201)

    def _student_messages(self, application_id: int):
        try:
            payload = self._read_json_request() if self.command == "POST" else {}
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
            return

        def run(conn, user_id):
            student_id = student_service.student_id_for_user(conn, user_id)
            with conn.transaction():
                conn.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))
                if self.command == "POST":
                    return message_service.reply(conn, user_id, student_id, application_id, payload)
                return message_service.thread(conn, user_id, student_id, application_id)
        self._student_call(run, success_status=201 if self.command == "POST" else 200, authenticated=True)

    def _student_saved_list(self):
        def run(conn, user_id):
            student_id = student_service.student_id_for_user(conn, user_id)
            return {"saved": saved_service.list_saved(conn, student_id)}
        self._student_call(run, authenticated=True)

    def _student_saved_change(self, listing_id: int):
        def run(conn, user_id):
            student_id = student_service.student_id_for_user(conn, user_id)
            with conn.transaction():
                if self.command == "PUT":
                    return saved_service.save(conn, student_id, listing_id)
                return saved_service.unsave(conn, student_id, listing_id)
        self._student_call(run, authenticated=True)

    # ---------- CV upload ----------

    def _read_file_body(self, max_bytes: int) -> bytes:
        """A raw upload body (not JSON), refusing anything over max_bytes."""
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            raise student_service.StudentError(400, "INVALID_CONTENT_LENGTH", "Invalid request length.") from None
        if length <= 0:
            raise student_service.StudentError(422, "EMPTY_CV", "Choose a file to upload.")
        if length > max_bytes:
            raise student_service.StudentError(413, "CV_TOO_LARGE", "Your CV must be 4 MB or smaller.")
        return self.rfile.read(length)

    def _student_cv(self):
        try:
            data = self._read_file_body(cv_service.MAX_CV_BYTES) if self.command == "PUT" else b""
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
            return
        filename = parse_qs(urlsplit(self.path).query).get("filename", [None])[-1]

        def run(conn, user_id):
            student_id = student_service.student_id_for_user(conn, user_id)
            if self.command == "GET":
                return cv_service.cv_info(conn, student_id)
            with conn.transaction():
                conn.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))
                if self.command == "PUT":
                    return cv_service.save_cv(conn, student_id, data, filename)
                return cv_service.delete_cv(conn, student_id)
        self._student_call(run, authenticated=True)

    def _student_cv_file(self):
        def run(conn, user_id):
            return cv_service.read_cv(conn, student_service.student_id_for_user(conn, user_id))
        cv = self._student_run(run, authenticated=True)
        if cv is None:
            return  # error already sent
        body = bytes(cv["data"])
        self.send_response(200)
        self.send_header("Content-Type", cv["content_type"])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(cv['filename'])}")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    # ---------- job alerts ----------

    def _student_alerts(self):
        try:
            payload = self._read_json_request() if self.command == "POST" else {}
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
            return

        def run(conn, user_id):
            student_id = student_service.student_id_for_user(conn, user_id)
            if self.command == "GET":
                return {"alerts": alert_service.list_alerts(conn, student_id)}
            with conn.transaction():
                return alert_service.create_alert(conn, student_id, payload.get("filters"))
        self._student_call(run, success_status=201 if self.command == "POST" else 200, authenticated=True)

    def _student_alert_delete(self, alert_id: int):
        def run(conn, user_id):
            student_id = student_service.student_id_for_user(conn, user_id)
            with conn.transaction():
                return alert_service.delete_alert(conn, student_id, alert_id)
        self._student_call(run, authenticated=True)

    def _cron_job_alerts(self):
        """Daily job (vercel.json "crons"). Vercel sends Authorization: Bearer $CRON_SECRET."""
        secret = os.environ.get("CRON_SECRET")
        if not secret:
            self._send_json(503, {"error": {"code": "CONFIGURATION_ERROR", "message": "CRON_SECRET is not configured."}})
            return
        if not secrets.compare_digest(self.headers.get("Authorization", ""), f"Bearer {secret}"):
            self._send_json(401, {"error": {"code": "UNAUTHENTICATED", "message": "Not allowed."}})
            return
        try:
            self._require_email_configuration()
        except ConfigurationError as exc:
            self._send_json(503, {"error": {"code": "CONFIGURATION_ERROR", "message": str(exc)}})
            return
        site_url = self._site_url()
        self._student_call(lambda conn, _user_id: alert_service.run_alerts(conn, self._send_email, site_url))

    # ---------- coordinator invites ----------

    def _send_invite(self, invite: dict, raw_token: str):
        url = f"{self._site_url()}/accept-invite?token={quote(raw_token)}"
        self._send_email(
            invite["email"],
            f"You're invited to coordinate internships for {invite['university']} on InternLink",
            f"<p>Hello,</p><p>{escape(invite['inviter'])} invited you to join InternLink as an internship "
            f"coordinator for <b>{escape(invite['university'])}</b>. Coordinators verify students and approve "
            f"their placements.</p><p><a href=\"{escape(url)}\">Accept the invitation</a></p>"
            f"<p>This link expires in {invite['days']} days. If you weren't expecting it, you can ignore this email.</p>",
        )

    def _create_invite(self, conn, user_id: int, university_id: int, payload: dict, raw_token: str) -> dict:
        inviter = conn.execute("SELECT full_name FROM users WHERE user_id = %s", (user_id,)).fetchone()
        with conn.transaction():
            conn.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))
            return invite_service.invite_coordinator(
                conn, university_id, payload, raw_token, inviter_name=inviter["full_name"] if inviter else "InternLink"
            )

    def _invite_flow(self, university_for, allowed_roles: set[str]):
        """GET lists the university's coordinators; POST invites one and emails the link."""
        try:
            payload = self._read_json_request() if self.command == "POST" else {}
            if self.command == "POST":
                self._require_email_configuration()
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
            return
        except ConfigurationError as exc:
            self._send_json(503, {"error": {"code": "CONFIGURATION_ERROR", "message": str(exc)}})
            return
        raw_token = secrets.token_urlsafe(32)

        def run(conn, user_id):
            university_id = university_for(conn, user_id)
            if self.command == "GET":
                return {"coordinators": invite_service.list_coordinators(conn, university_id)}
            return {"invite": self._create_invite(conn, user_id, university_id, payload, raw_token)}

        result = self._role_run(run, allowed_roles)
        if result is None:
            return  # error already sent
        if self.command == "GET":
            self._send_json(200, result)
            return
        # The invite is saved (committed) before the email goes out.
        invite = result["invite"]
        try:
            self._send_invite(invite, raw_token)
        except ConfigurationError:
            self._send_json(503, {"error": {"code": "EMAIL_FAILED", "message": "The invite was saved but the email couldn't be sent. Try again in a minute."}})
            return
        self._send_json(201, {"invited": invite["email"], "message": f"Invitation sent to {invite['email']}."})

    def _admin_universities(self):
        self._role_call(lambda conn, _user_id: {"universities": invite_service.list_verified_universities(conn)}, {"admin"})

    def _admin_university_coordinators(self, university_id: int):
        self._invite_flow(lambda conn, _user_id: university_id, {"admin"})

    def _coordinator_coordinators(self):
        def own_university(conn, user_id):
            scope = self._coordinator_scope(conn, user_id)
            if self.command == "POST" and scope["department_id"] is not None:
                raise student_service.StudentError(403, "UNIVERSITY_COORDINATOR_REQUIRED", "Only a university-wide coordinator can invite colleagues.")
            return scope["university_id"]
        self._invite_flow(own_university, {"coordinator"})

    def _invite_details(self):
        token = parse_qs(urlsplit(self.path).query).get("token", [""])[-1]
        self._student_call(lambda conn, _user_id: {"invite": invite_service.invite_details(conn, token)})

    def _accept_invite(self):
        try:
            payload = self._read_json_request()
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
            return

        def accept(conn, _user_id):
            with conn.transaction():
                return invite_service.accept_invite(conn, payload.get("token"), payload)
        self._student_call(accept)

    def _student_withdraw_application(self, application_id: int):
        try:
            user_id = self._student_user_id()
            with self._student_connection() as conn:
                student_id = student_service.student_id_for_user(conn, user_id)
                with conn.transaction():
                    conn.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))
                    result = student_service.withdraw_application(conn, student_id, application_id)
            self._send_json(200, {"application": result})
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
        except ConfigurationError as exc:
            self._send_json(503, {"error": {"code": "CONFIGURATION_ERROR", "message": str(exc)}})
        except psycopg.Error:
            logger.exception("Student application withdrawal failed")
            self._send_json(503, {"error": {"code": "SERVICE_UNAVAILABLE", "message": "The student service is temporarily unavailable."}})

    def _student_notifications(self):
        try:
            user_id = self._student_user_id()
            with self._student_connection() as conn:
                student_service.student_id_for_user(conn, user_id)
                notifications = student_service.list_notifications(conn, user_id)
            self._send_json(200, {"notifications": notifications})
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
        except ConfigurationError as exc:
            self._send_json(503, {"error": {"code": "CONFIGURATION_ERROR", "message": str(exc)}})
        except psycopg.Error:
            logger.exception("Student notifications request failed")
            self._send_json(503, {"error": {"code": "SERVICE_UNAVAILABLE", "message": "The student service is temporarily unavailable."}})

    def _student_mark_notification_read(self, notification_id: int):
        try:
            user_id = self._student_user_id()
            with self._student_connection() as conn:
                student_service.student_id_for_user(conn, user_id)
                with conn.transaction():
                    result = student_service.mark_notification_read(conn, user_id, notification_id)
            self._send_json(200, result)
        except student_service.StudentError as exc:
            self._send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
        except ConfigurationError as exc:
            self._send_json(503, {"error": {"code": "CONFIGURATION_ERROR", "message": str(exc)}})
        except psycopg.Error:
            logger.exception("Student notification update failed")
            self._send_json(503, {"error": {"code": "SERVICE_UNAVAILABLE", "message": "The student service is temporarily unavailable."}})

    def _recommendations(self):
        secret = os.environ.get("INTERNLINK_JWT_SECRET")
        if not secret:
            self._send_json(
                503,
                {"error": {"code": "CONFIGURATION_ERROR", "message": "INTERNLINK_JWT_SECRET is not configured"}},
            )
            return

        authorization = self.headers.get("Authorization", "")
        scheme, separator, credentials = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator or not credentials:
            self._send_json(
                401,
                {"detail": "Not logged in"},
                (("WWW-Authenticate", "Bearer"),),
            )
            return

        try:
            claims = jwt.decode(
                credentials,
                secret,
                algorithms=["HS256"],
                options={"require": ["exp", "sub", "role"]},
            )
        except jwt.PyJWTError:
            self._send_json(
                401,
                {"detail": "Invalid or expired token"},
                (("WWW-Authenticate", "Bearer"),),
            )
            return
        if claims["role"] != "student":
            self._send_json(403, {"detail": "Only students can get recommendations"})
            return

        try:
            user_id = int(claims["sub"])
        except (TypeError, ValueError, OverflowError):
            self._send_json(
                401,
                {"detail": "Invalid or expired token"},
                (("WWW-Authenticate", "Bearer"),),
            )
            return

        raw_limit = parse_qs(urlsplit(self.path).query, keep_blank_values=True).get(
            "limit", [str(DEFAULT_CONFIG.default_k)]
        )[0]
        try:
            limit = int(raw_limit)
        except ValueError:
            self._send_json(422, {"detail": "Invalid limit"})
            return
        if not 1 <= limit <= DEFAULT_CONFIG.max_k:
            self._send_json(422, {"detail": "Invalid limit"})
            return

        try:
            pool = _get_matching_pool()
            with pool.connection() as conn:
                student_id = student_id_for_user(conn, user_id)
                if student_id is None:
                    raise ProfileIncomplete("No student profile")
                result = recommend_for_student(
                    conn, student_id, k=limit, cfg=DEFAULT_CONFIG
                )
        except ConfigurationError as exc:
            self._send_json(
                503,
                {"error": {"code": "CONFIGURATION_ERROR", "message": str(exc)}},
            )
            return
        except ProfileIncomplete:
            self._send_json(
                422,
                {
                    "error": {
                        "code": "PROFILE_INCOMPLETE",
                        "message": "Add your programme and at least one skill to get recommendations",
                    }
                },
            )
            return
        except (MatchingUnavailable, psycopg.Error):
            logger.exception("Recommendation lookup failed for user %s", user_id)
            self._send_json(
                503,
                {
                    "error": {
                        "code": "MATCHING_UNAVAILABLE",
                        "message": "Couldn't load recommendations. Please retry.",
                    }
                },
            )
            return

        self._send_json(
            200,
            {
                "algorithm": result.algorithm,
                "count": result.count,
                "results": [vars(recommendation) for recommendation in result.results],
            },
        )

    def _employer_request(self, path: str):
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            self._send_json(400, {"detail": "Invalid Content-Length"})
            return
        if length < 0:
            self._send_json(400, {"detail": "Invalid Content-Length"})
            return
        if length > MAX_REQUEST_BYTES:
            self._send_json(
                413,
                {
                    "ok": False,
                    "category": "invalid",
                    "message": "Request body is too large.",
                    "fields": {},
                },
            )
            return
        body = self.rfile.read(length) if length else b""

        db = None
        try:
            context, db = _build_employer_context()
            environ = {
                "REQUEST_METHOD": self.command,
                "PATH_INFO": path,
                "QUERY_STRING": urlsplit(self.path).query,
                "CONTENT_LENGTH": str(len(body)),
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "SERVER_NAME": "vercel",
                "SERVER_PORT": self.headers.get("X-Forwarded-Port", "443"),
                "SERVER_PROTOCOL": self.request_version,
                "wsgi.version": (1, 0),
                "wsgi.url_scheme": self.headers.get("X-Forwarded-Proto", "https"),
                "wsgi.input": BytesIO(body),
                "wsgi.errors": sys.stderr,
                "wsgi.multithread": False,
                "wsgi.multiprocess": True,
                "wsgi.run_once": True,
            }
            for name, value in self.headers.items():
                key = name.upper().replace("-", "_")
                if key not in {"CONTENT_TYPE", "CONTENT_LENGTH"}:
                    environ[f"HTTP_{key}"] = value

            response = {}

            def start_response(status, headers, exc_info=None):
                if exc_info and "status" in response:
                    raise exc_info[1].with_traceback(exc_info[2])
                response["status"] = status
                response["headers"] = headers

            chunks = EmployerAPI(context)(environ, start_response)
            try:
                response_body = b"".join(chunks)
            finally:
                close = getattr(chunks, "close", None)
                if close:
                    close()

            status = int(response["status"].split(" ", 1)[0])
            self.send_response(status)
            for name, value in response["headers"]:
                self.send_header(name, value)
            self.end_headers()
            if response_body:
                self.wfile.write(response_body)
        except ConfigurationError as exc:
            self._send_json(
                503,
                {"ok": False, "category": "server", "message": str(exc), "fields": {}},
            )
        except Exception:
            logger.exception("Employer API request failed")
            self._send_json(
                503,
                {
                    "ok": False,
                    "category": "server",
                    "message": "Employer service is unavailable.",
                    "fields": {},
                },
            )
        finally:
            if db is not None:
                db.close()

    def _send_json(self, status: int, payload: dict, headers=()):
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, format, *args):
        logger.info("%s - %s", self.address_string(), format % args)
