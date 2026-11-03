"""
auth_utils.py - passwords, sessions, the student_required guard, rate limiting, audit log.

Used by other files like this:

    from auth_utils import student_required

    @route("GET", "/api/profile")
    @student_required                      # <- keep this line BELOW @route
    def get_profile(req):
        student_id = req.user["student_id"]
        ...
"""
import functools
import hashlib
import re
import secrets
import threading
import time
import traceback

import bcrypt
from psycopg2.extras import Json

import config
import db
from router import HttpError

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")     # same idea as ck_users_email
MAX_PASSWORD_BYTES = 72                                    # bcrypt only reads 72 bytes


# ---------------------------------------------------------------------
# Email helpers
# ---------------------------------------------------------------------
def normalize_email(email):
    """users.email must be stored in lower case."""
    return (email or "").strip().lower()


def is_valid_email(email):
    return bool(email) and len(email) <= 254 and bool(_EMAIL_RE.match(email))


def email_matches_domain(email, university_domain):
    """
    True if the email belongs to the university domain.
    'a@must.ac.ug' and 'a@std.must.ac.ug' match 'must.ac.ug'; 'a@evilmust.ac.ug' does not.
    """
    if "@" not in email:
        return False
    domain = email.rsplit("@", 1)[1].lower()
    base = (university_domain or "").lower()
    return bool(base) and (domain == base or domain.endswith("." + base))


# ---------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------
def validate_password(password):
    """Return an error message, or None when the password is acceptable."""
    if not isinstance(password, str) or len(password) < config.MIN_PASSWORD_LENGTH:
        return f"Password must be at least {config.MIN_PASSWORD_LENGTH} characters."
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return "Password is too long (maximum 72 characters)."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Password must contain at least one letter and one number."
    return None


def hash_password(password):
    """bcrypt hash, cost 12 (users.password_hash comment). The plain password is never stored."""
    return bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt(rounds=config.BCRYPT_ROUNDS)
    ).decode("utf-8")


def verify_password(password, password_hash):
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


_dummy_hash = None


def burn_password_time(password):
    """
    Used when the email does not exist. It spends the same time as a real check,
    so attackers cannot tell 'unknown email' from 'wrong password' by timing.
    """
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password("dummy-password-1")
    verify_password(password, _dummy_hash)


# ---------------------------------------------------------------------
# Sessions (in memory; restarting the server logs everybody out)
# ---------------------------------------------------------------------
_sessions = {}
_sessions_lock = threading.Lock()


def _session_key(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()   # only a hash is kept in memory


def create_session(user_id):
    """Create a session and return the random token to put in the cookie."""
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _sessions_lock:
        for key in [k for k, s in _sessions.items() if s["expires"] <= now]:
            del _sessions[key]                                   # clean out expired sessions
        _sessions[_session_key(token)] = {
            "user_id": user_id,
            "created": now,
            "expires": now + config.SESSION_HOURS * 3600,
        }
    return token


def get_session(token):
    if not token:
        return None
    with _sessions_lock:
        session = _sessions.get(_session_key(token))
        if session is None:
            return None
        if session["expires"] <= time.time():
            del _sessions[_session_key(token)]
            return None
        return dict(session)


def destroy_session(token):
    if not token:
        return
    with _sessions_lock:
        _sessions.pop(_session_key(token), None)


def destroy_user_sessions(user_id):
    """Log a user out of every device (use after a password change)."""
    with _sessions_lock:
        for key in [k for k, s in _sessions.items() if s["user_id"] == user_id]:
            del _sessions[key]


def set_session_cookie(response, token):
    response.set_cookie(config.SESSION_COOKIE, token, max_age=config.SESSION_HOURS * 3600)
    return response


def clear_session_cookie(response):
    response.clear_cookie(config.SESSION_COOKIE)
    return response


# ---------------------------------------------------------------------
# The guard for every student route
# ---------------------------------------------------------------------
def student_required(handler):
    """
    Allows the request only if the user is logged in AND is an active student.
    Sets req.user (a dict) and req.session for the handler.
    The database is checked on every request, so a suspended account stops working at once.
    """
    @functools.wraps(handler)
    def wrapper(req):
        token = req.cookies.get(config.SESSION_COOKIE)
        session = get_session(token)
        if session is None:
            raise HttpError(401, "Please log in to continue.")

        user = db.fetch_one(
            """
            SELECT u.user_id, u.email, u.full_name, u.phone, u.status,
                   sp.student_id, sp.university_id, sp.department_id,
                   sp.programme_id, sp.verified
            FROM users u
            JOIN student_profiles sp ON sp.user_id = u.user_id
            WHERE u.user_id = %s AND u.role = 'student'
            """,
            (session["user_id"],),
        )
        if user is None:
            destroy_session(token)
            raise HttpError(401, "Please log in to continue.")
        if user["status"] != "active":
            destroy_session(token)
            raise HttpError(403, "Your account is not active.")

        req.user = user
        req.session = session
        return handler(req)
    return wrapper


# ---------------------------------------------------------------------
# Rate limiting (per key, in memory)
# ---------------------------------------------------------------------
_rate_hits = {}
_rate_lock = threading.Lock()


def check_rate_limit(key, max_attempts, window_seconds):
    """Raise 429 if 'key' (for example 'login:127.0.0.1') made too many attempts recently."""
    now = time.time()
    with _rate_lock:
        if len(_rate_hits) > 10000:
            _rate_hits.clear()
        hits = [t for t in _rate_hits.get(key, []) if now - t < window_seconds]
        if len(hits) >= max_attempts:
            _rate_hits[key] = hits
            raise HttpError(429, "Too many attempts. Please wait a while and try again.")
        hits.append(now)
        _rate_hits[key] = hits


# ---------------------------------------------------------------------
# Audit log (table audit_logs, SR19)
# ---------------------------------------------------------------------
def audit(action, user_id=None, role=None, ip=None, resource_type=None,
          resource_id=None, result="success", details=None):
    """
    Write one audit row. A failure here is printed but never breaks the request.
    Never put passwords, tokens or CV contents in 'details'.
    """
    try:
        db.execute(
            """
            INSERT INTO audit_logs
                (actor_user_id, actor_role, action, resource_type, resource_id,
                 ip_address, result, details)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (user_id, role, action, resource_type,
             None if resource_id is None else str(resource_id),
             ip, result, Json(details) if details else None),
            user_id=user_id,
        )
    except Exception:
        print("WARNING: could not write audit log entry:", action)
        traceback.print_exc()


# Quick self-test (needs no database):  python auth_utils.py
if __name__ == "__main__":
    print("Hashing (takes about a second)...")
    hashed = hash_password("Test1234")
    print("1. hash length:", len(hashed), "| starts with $2:", hashed.startswith("$2"))
    print("2. right password:", verify_password("Test1234", hashed),
          "| wrong password:", verify_password("wrong", hashed))

    cases = [("too short", "short1"), ("no number", "alllettersonly"),
             ("no letter", "12345678"), ("good", "Good1234"), ("too long", "x" * 80 + "1")]
    for label, pw in cases:
        print(f"3. {label:<10} -> {validate_password(pw)}")

    token = create_session(7)
    print("4. session user:", get_session(token)["user_id"])
    destroy_session(token)
    print("5. after logout:", get_session(token))

    print("6. email format:", is_valid_email("a@std.must.ac.ug"), is_valid_email("bad@"))
    print("7. domain match:", email_matches_domain("a@std.must.ac.ug", "must.ac.ug"),
          email_matches_domain("a@evilmust.ac.ug", "must.ac.ug"))

    try:
        for attempt in range(1, 4):
            check_rate_limit("selftest", 2, 60)
    except HttpError as exc:
        print(f"8. rate limit stopped attempt {attempt} -> {exc.status}")