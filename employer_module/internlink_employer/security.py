"""Password hashing, opaque tokens and the reference bearer-token service.

The design document uses ``bcrypt`` and the Auth module (4.2.1) owns token
verification.  Because this module must run on vanilla Python, passwords use
PBKDF2-HMAC-SHA256 from ``hashlib`` and the reference token service uses
HMAC-SHA256.  Both are deliberately behind small, replaceable interfaces so the
real Auth module can be supplied at integration time.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import timedelta
from typing import Any

PBKDF2_ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 600_000
SALT_BYTES = 16


class PasswordHashingError(ValueError):
    """Raised when a stored password hash has an unknown format."""


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    """Hash a password into a self-describing, verifiable string.

    Format: ``pbkdf2_sha256$<iterations>$<salt-b64>$<hash-b64>``.
    A fresh random salt is generated for every call.
    """

    if not isinstance(password, str) or not password:
        raise ValueError("password must be a non-empty string")
    if iterations < 1:
        raise ValueError("iterations must be positive")
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$".join(
        (
            PBKDF2_ALGORITHM,
            str(iterations),
            _b64url_encode(salt),
            _b64url_encode(digest),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time verification of a password against a stored hash."""

    if not isinstance(password, str) or not isinstance(encoded, str):
        return False
    try:
        algorithm, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != PBKDF2_ALGORITHM:
            return False
        iterations = int(iterations_text)
        salt = _b64url_decode(salt_text)
        expected = _b64url_decode(digest_text)
    except (ValueError, TypeError):
        return False
    if iterations < 1 or len(salt) < 8 or len(expected) != 32:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def new_token() -> str:
    """Return a cryptographically random URL-safe token (256 bits)."""

    return secrets.token_urlsafe(32)


def hash_token(raw_token: str) -> str:
    """Hash a bearer/verification token before it touches the database."""

    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def verification_link(base_url: str, raw_token: str) -> str:
    base = (base_url or "").rstrip("/")
    return f"{base}/verify-email?token={raw_token}"


class ReferenceTokenService:
    """Small HMAC-signed bearer token service used for local integration tests.

    Production deployments should inject the Auth module's implementation
    instead.  ``verify_token`` returns ``None`` for anything invalid, expired or
    malformed; that is exactly the contract ``open_session`` relies on.
    """

    def __init__(self, secret: str | bytes, *, default_ttl: timedelta = timedelta(hours=8)):
        if isinstance(secret, str):
            secret = secret.encode("utf-8")
        if not isinstance(secret, (bytes, bytearray)) or len(secret) < 32:
            raise ValueError("token secret must contain at least 32 bytes")
        self._secret = bytes(secret)
        self._default_ttl = default_ttl

    def issue_token(
        self,
        user_id: int,
        role: str = "employer",
        *,
        ttl: timedelta | None = None,
    ) -> str:
        ttl = ttl or self._default_ttl
        now = int(time.time())
        payload = {
            "user_id": int(user_id),
            "role": role,
            "iat": now,
            "exp": now + int(ttl.total_seconds()),
        }
        body = _b64url_encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        signature = hmac.new(self._secret, body.encode("ascii"), hashlib.sha256).digest()
        return f"{body}.{_b64url_encode(signature)}"

    def verify_token(self, token: str | None) -> dict[str, Any] | None:
        if not token or not isinstance(token, str):
            return None
        try:
            body, signature_text = token.split(".", 1)
            supplied_signature = _b64url_decode(signature_text)
            # Reject non-canonical base64: trailing padding bits must not create
            # multiple valid strings for the same signature bytes.
            if _b64url_encode(supplied_signature) != signature_text:
                return None
            expected_signature = hmac.new(
                self._secret, body.encode("ascii"), hashlib.sha256
            ).digest()
            if not hmac.compare_digest(supplied_signature, expected_signature):
                return None
            raw_body = _b64url_decode(body)
            if _b64url_encode(raw_body) != body:
                return None
            claims = json.loads(raw_body.decode("utf-8"))
            if not isinstance(claims, dict):
                return None
            user_id = int(claims["user_id"])
            expires_at = int(claims["exp"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None
        if expires_at < int(time.time()) or user_id <= 0:
            return None
        claims["user_id"] = user_id
        return claims
