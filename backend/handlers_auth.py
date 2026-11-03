"""
handlers_auth.py - student sign-up, email verification, login, logout, "who am I".

Routes:
    POST /api/auth/signup
    GET  /api/auth/verify-email?token=...
    POST /api/auth/login
    POST /api/auth/logout
    GET  /api/auth/me
"""
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

from psycopg2 import errors as pg_errors

import auth_utils
import config
import db
from router import HttpError, Response, json_response, route

GENERIC_LOGIN_ERROR = "Incorrect email or password."
VERIFY_TOKEN_HOURS = 24
_PHONE_RE = re.compile(r"^\+?[0-9][0-9 \-]{6,18}[0-9]$")
_STUDENT_NUMBER_RE = re.compile(r"^[A-Za-z0-9/\-_. ]+$")


# ---------------------------------------------------------------------
# Small validation helpers
# ---------------------------------------------------------------------
def _clean_text(value, label, max_len, required=True, min_len=1):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise HttpError(400, f"{label} must be text.")
    value = value.strip()
    if not value:
        if required:
            raise HttpError(400, f"{label} is required.")
        return None
    if len(value) < min_len or len(value) > max_len:
        raise HttpError(400, f"{label} must be between {min_len} and {max_len} characters.")
    return value


def _clean_id(value, label):
    if isinstance(value, (bool, float)) or value is None:
        raise HttpError(400, f"Please choose a valid {label}.")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise HttpError(400, f"Please choose a valid {label}.")
    if number < 1 or number > 10 ** 18:
        raise HttpError(400, f"Please choose a valid {label}.")
    return number


def student_summary(user_id):
    """Profile summary used by /me and by login."""
    return db.fetch_one(
        """
        SELECT u.user_id, u.email, u.full_name, u.phone, u.last_login_at,
               sp.student_id, sp.student_number, sp.year_of_study, sp.verified,
               sp.university_id, un.name AS university_name,
               sp.department_id, d.name AS department_name,
               sp.programme_id, p.name AS programme_name
        FROM users u
        JOIN student_profiles sp ON sp.user_id = u.user_id
        JOIN universities un     ON un.university_id = sp.university_id
        JOIN departments d       ON d.department_id = sp.department_id
        JOIN programmes p        ON p.programme_id = sp.programme_id
        WHERE u.user_id = %s AND u.role = 'student'
        """,
        (user_id,),
    )


# ---------------------------------------------------------------------
# Sign up
# ---------------------------------------------------------------------
@route("POST", "/api/auth/signup")
def signup(req):
    auth_utils.check_rate_limit(f"signup:{req.client_ip}", 10, 3600)
    body = req.json()

    full_name = _clean_text(body.get("full_name"), "Full name", 100, min_len=2)
    phone = _clean_text(body.get("phone"), "Phone number", 20, required=False)
    if phone and not _PHONE_RE.match(phone):
        raise HttpError(400, "Phone number is not valid. Example: +256 700 000000")

    raw_email = body.get("email")
    if not isinstance(raw_email, str):
        raise HttpError(400, "Email is required.")
    email = auth_utils.normalize_email(raw_email)
    if not auth_utils.is_valid_email(email):
        raise HttpError(400, "Please enter a valid email address.")

    password = body.get("password")
    problem = auth_utils.validate_password(password)
    if problem:
        raise HttpError(400, problem)

    student_number = _clean_text(body.get("student_number"), "Student number", 40)
    if not _STUDENT_NUMBER_RE.match(student_number):
        raise HttpError(400, "Student number can only contain letters, numbers, / - _ . and spaces.")

    year = body.get("year_of_study")
    if isinstance(year, bool) or isinstance(year, float):
        raise HttpError(400, "Year of study must be a number from 1 to 6.")
    try:
        year = int(year)
    except (TypeError, ValueError):
        raise HttpError(400, "Year of study must be a number from 1 to 6.")
    if not 1 <= year <= 6:
        raise HttpError(400, "Year of study must be a number from 1 to 6.")

    university_id = _clean_id(body.get("university_id"), "university")
    department_id = _clean_id(body.get("department_id"), "department")
    programme_id = _clean_id(body.get("programme_id"), "programme")

    # --- University must be verified and the email must belong to it (SR18) ---
    university = db.fetch_one(
        "SELECT university_id, email_domain, status FROM universities WHERE university_id = %s",
        (university_id,),
    )
    if university is None or university["status"] != "verified":
        raise HttpError(400, "Please choose a university that is registered on InternLink.")
    if not auth_utils.email_matches_domain(email, university["email_domain"]):
        raise HttpError(400, f"Please use your university email address (ending in @{university['email_domain']}).")

    # --- Department must belong to the university, programme to the department ---
    chain = db.fetch_one(
        """
        SELECT 1 AS ok
        FROM departments d
        JOIN programmes p ON p.department_id = d.department_id
        WHERE d.department_id = %s AND d.university_id = %s AND p.programme_id = %s
        """,
        (department_id, university_id, programme_id),
    )
    if chain is None:
        raise HttpError(400, "The department or programme does not match the university you chose.")

    password_hash = auth_utils.hash_password(password)
    auto_verify = config.AUTO_VERIFY_EMAIL
    verify_token = None

    try:
        with db.transaction() as cur:
            cur.execute(
                """
                INSERT INTO users (email, password_hash, full_name, phone, role, status, email_verified_at)
                VALUES (%s, %s, %s, %s, 'student', %s, %s)
                RETURNING user_id
                """,
                (email, password_hash, full_name, phone,
                 "active" if auto_verify else "pending",
                 datetime.now(timezone.utc) if auto_verify else None),
            )
            user_id = cur.fetchone()["user_id"]

            cur.execute(
                """
                INSERT INTO student_profiles
                    (user_id, university_id, department_id, programme_id, student_number, year_of_study)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (user_id, university_id, department_id, programme_id, student_number, year),
            )

            if not auto_verify:
                verify_token = secrets.token_urlsafe(32)
                cur.execute(
                    """
                    INSERT INTO auth_tokens (user_id, purpose, token_hash, expires_at, ip_address)
                    VALUES (%s, 'email_verify', %s, %s, %s)
                    """,
                    (user_id, hashlib.sha256(verify_token.encode("utf-8")).hexdigest(),
                     datetime.now(timezone.utc) + timedelta(hours=VERIFY_TOKEN_HOURS), req.client_ip),
                )
    except pg_errors.UniqueViolation as exc:
        name = exc.diag.constraint_name or ""
        if name == "uq_users_email":
            raise HttpError(409, "An account with this email already exists. Try logging in.")
        if name == "uq_student_number":
            raise HttpError(409, "That student number is already registered at this university.")
        raise HttpError(409, "This account already exists.")
    except pg_errors.RaiseException as exc:                 # a message raised on purpose by a trigger
        raise HttpError(400, (exc.diag.message_primary or "Sign-up was not accepted.")[:200])
    except (pg_errors.CheckViolation, pg_errors.ForeignKeyViolation):
        raise HttpError(400, "Some of the details were not accepted. Please check them and try again.")

    auth_utils.audit("signup", user_id, "student", req.client_ip, "users", user_id)

    if verify_token:
        # No mail server yet: the link is printed in the terminal running server.py
        print(f"[DEV] Email verification link for {email}:\n"
              f"      http://{config.HOST}:{config.PORT}/api/auth/verify-email?token={verify_token}")

    return {
        "message": ("Account created. You can now log in." if auto_verify
                    else "Account created. Check your email for the verification link."),
        "verification_required": not auto_verify,
        "email": email,
    }, 201


# ---------------------------------------------------------------------
# Email verification (only used when AUTO_VERIFY_EMAIL=false)
# ---------------------------------------------------------------------
@route("GET", "/api/auth/verify-email")
def verify_email(req):
    auth_utils.check_rate_limit(f"verify:{req.client_ip}", 20, 600)
    token = req.query.get("token", "")
    verified = False

    if 20 <= len(token) <= 200:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with db.transaction() as cur:
            cur.execute(
                """
                UPDATE auth_tokens SET used_at = now()
                WHERE token_hash = %s AND purpose = 'email_verify'
                  AND used_at IS NULL AND revoked_at IS NULL AND expires_at > now()
                RETURNING user_id
                """,
                (token_hash,),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    """
                    UPDATE users
                    SET email_verified_at = COALESCE(email_verified_at, now()),
                        status = CASE WHEN status = 'pending' THEN 'active' ELSE status END
                    WHERE user_id = %s AND role = 'student'
                    RETURNING user_id
                    """,
                    (row["user_id"],),
                )
                verified = cur.fetchone() is not None
                if verified:
                    auth_utils.audit("email_verified", row["user_id"], "student", req.client_ip, "users", row["user_id"])

    target = "/index.html?verified=1" if verified else "/index.html?verified=0"
    return Response(b"", 302, "text/plain; charset=utf-8", headers=[("Location", target)])


# ---------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------
@route("POST", "/api/auth/login")
def login(req):
    ip = req.client_ip
    auth_utils.check_rate_limit(f"login:{ip}", 15, 300)
    body = req.json()

    raw_email = body.get("email")
    password = body.get("password")
    if not isinstance(raw_email, str) or not isinstance(password, str) or not password or len(password) > 200:
        raise HttpError(401, GENERIC_LOGIN_ERROR)
    email = auth_utils.normalize_email(raw_email)
    if not auth_utils.is_valid_email(email):
        raise HttpError(401, GENERIC_LOGIN_ERROR)

    user = db.fetch_one(
        """
        SELECT u.user_id, u.password_hash, u.status,
               (u.locked_until IS NOT NULL AND u.locked_until > now()) AS is_locked,
               GREATEST(1, CEIL(EXTRACT(EPOCH FROM (u.locked_until - now())) / 60))::int AS lock_minutes
        FROM users u
        WHERE lower(u.email) = %s AND u.role = 'student'
          AND EXISTS (SELECT 1 FROM student_profiles sp WHERE sp.user_id = u.user_id)
        """,
        (email,),
    )

    if user is None:
        auth_utils.burn_password_time(password)             # same timing as a real account
        auth_utils.audit("login_failed", None, None, ip, "users", None, "failure",
                         {"reason": "unknown_account"})
        raise HttpError(401, GENERIC_LOGIN_ERROR)

    user_id = user["user_id"]

    if user["is_locked"]:
        auth_utils.audit("login_blocked_locked", user_id, "student", ip, "users", user_id, "denied")
        raise HttpError(423, f"Too many failed attempts. Try again in about {user['lock_minutes']} minute(s).")

    if not auth_utils.verify_password(password, user["password_hash"]):
        # Atomic: count the failure, and lock the account on the 5th one.
        result = db.fetch_one(
            """
            UPDATE users
            SET failed_login_count = CASE WHEN failed_login_count + 1 >= %s THEN 0
                                          ELSE failed_login_count + 1 END,
                locked_until = CASE WHEN failed_login_count + 1 >= %s
                                    THEN now() + make_interval(mins => %s)
                                    ELSE locked_until END
            WHERE user_id = %s
            RETURNING (locked_until IS NOT NULL AND locked_until > now()) AS now_locked
            """,
            (config.MAX_FAILED_LOGINS, config.MAX_FAILED_LOGINS, config.LOCK_MINUTES, user_id),
        )
        if result and result["now_locked"]:
            auth_utils.audit("account_locked", user_id, "student", ip, "users", user_id, "denied")
            raise HttpError(423, f"Too many failed attempts. Your account is locked for {config.LOCK_MINUTES} minutes.")
        auth_utils.audit("login_failed", user_id, "student", ip, "users", user_id, "failure",
                         {"reason": "wrong_password"})
        raise HttpError(401, GENERIC_LOGIN_ERROR)

    # Password is correct - now check the account status.
    if user["status"] == "pending":
        raise HttpError(403, "Please verify your email address first. Check your inbox for the link.")
    if user["status"] != "active":
        auth_utils.audit("login_denied_status", user_id, "student", ip, "users", user_id, "denied",
                         {"status": user["status"]})
        raise HttpError(403, "This account is not active. Please contact your university coordinator.")

    db.execute(
        "UPDATE users SET failed_login_count = 0, locked_until = NULL, last_login_at = now() WHERE user_id = %s",
        (user_id,),
        user_id=user_id,
    )
    token = auth_utils.create_session(user_id)
    auth_utils.audit("login", user_id, "student", ip, "users", user_id)

    response = json_response({"message": "Logged in.", "user": student_summary(user_id)})
    return auth_utils.set_session_cookie(response, token)


# ---------------------------------------------------------------------
# Logout and "who am I"
# ---------------------------------------------------------------------
@route("POST", "/api/auth/logout")
def logout(req):
    token = req.cookies.get(config.SESSION_COOKIE)
    session = auth_utils.get_session(token)
    auth_utils.destroy_session(token)
    if session:
        auth_utils.audit("logout", session["user_id"], "student", req.client_ip, "users", session["user_id"])
    return auth_utils.clear_session_cookie(json_response({"message": "Logged out."}))


@route("GET", "/api/auth/me")
@auth_utils.student_required
def me(req):
    return {"user": student_summary(req.user["user_id"])}


# ---------------------------------------------------------------------
# Self-test:  python handlers_auth.py
# Needs the database. It creates TWO test student accounts that stay in the database
# (audit_logs is append-only, so they cannot be deleted). Account A is printed at the
# end so you can log in with it later.
# ---------------------------------------------------------------------
if __name__ == "__main__":
    import json

    from router import Request, router

    def call(method, path, body=None, cookie=None):
        headers = {"X-Requested-With": "InternLink", "Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = f"{config.SESSION_COOKIE}={cookie}"
        raw = json.dumps(body).encode("utf-8") if body is not None else b""
        resp = router.dispatch(Request(method, path, headers, raw, "127.0.0.1"))
        data = json.loads(resp.body) if resp.body else {}
        new_cookie = None
        for name, value in resp.headers:
            if name == "Set-Cookie" and value.startswith(config.SESSION_COOKIE + "=") and "Max-Age=0" not in value:
                new_cookie = value.split(";", 1)[0].split("=", 1)[1]
        return resp.status, data, new_cookie

    failures = []

    def check(label, got, expected):
        good = got == expected
        if not good:
            failures.append(label)
        print(f"{'OK  ' if good else 'FAIL'} {label:<44} status {got}" + ("" if good else f" (expected {expected})"))

    try:
        target = db.fetch_one(
            """
            SELECT un.university_id, un.email_domain, d.department_id, p.programme_id
            FROM universities un
            JOIN departments d ON d.university_id = un.university_id
            JOIN programmes p ON p.department_id = d.department_id
            WHERE un.status = 'verified'
            ORDER BY un.university_id, d.department_id, p.programme_id LIMIT 1
            """
        )
        if target is None:
            print("Cannot test: there is no verified university with a department and programme.")
            print("Check that 05_seed.sql was run and the seed universities have status 'verified'.")
            raise SystemExit(1)

        password = "Test1234x"

        def new_account(label):
            tag = secrets.token_hex(4)
            return {
                "full_name": f"Test Student {label}",
                "email": f"test.{tag}@{target['email_domain']}",
                "password": password,
                "student_number": f"T{tag.upper()}",
                "year_of_study": 2,
                "university_id": target["university_id"],
                "department_id": target["department_id"],
                "programme_id": target["programme_id"],
            }

        acct_a, acct_b = new_account("A"), new_account("B")

        status, _, _ = call("POST", "/api/auth/signup", acct_a)
        check("sign up account A", status, 201)
        status, _, _ = call("POST", "/api/auth/signup", acct_a)
        check("sign up same email again is refused", status, 409)
        status, _, _ = call("POST", "/api/auth/signup", dict(new_account("X"), email="someone@gmail.com"))
        check("sign up with a non-university email", status, 400)
        status, _, _ = call("POST", "/api/auth/signup", dict(new_account("X"), password="weak"))
        check("sign up with a weak password", status, 400)

        if not config.AUTO_VERIFY_EMAIL:
            print("\nAUTO_VERIFY_EMAIL is false, so login tests are skipped.")
            print("Open the [DEV] verification link printed above, then log in through the website.")
        else:
            status, _, _ = call("POST", "/api/auth/login", {"email": acct_a["email"], "password": "WrongPass1"})
            check("login with wrong password", status, 401)
            status, data, cookie = call("POST", "/api/auth/login", {"email": acct_a["email"], "password": password})
            check("login with correct password", status, 200)
            check("session cookie was set", bool(cookie), True)
            status, data, _ = call("GET", "/api/auth/me", cookie=cookie)
            check("/me while logged in", status, 200)
            check("/me returns the right email", data.get("user", {}).get("email"), acct_a["email"])
            status, _, _ = call("GET", "/api/auth/me")
            check("/me without a cookie", status, 401)
            status, _, _ = call("POST", "/api/auth/logout", cookie=cookie)
            check("logout", status, 200)
            status, _, _ = call("GET", "/api/auth/me", cookie=cookie)
            check("/me after logout", status, 401)

            call("POST", "/api/auth/signup", acct_b)
            codes = [call("POST", "/api/auth/login", {"email": acct_b["email"], "password": "WrongPass1"})[0]
                     for _ in range(config.MAX_FAILED_LOGINS)]
            check(f"{config.MAX_FAILED_LOGINS} wrong passwords (last one locks)",
                  codes, [401] * (config.MAX_FAILED_LOGINS - 1) + [423])
            status, _, _ = call("POST", "/api/auth/login", {"email": acct_b["email"], "password": password})
            check("correct password while locked", status, 423)

            print(f"\nTest account you can log in with later:\n  email:    {acct_a['email']}\n  password: {password}")

        print("\nAll checks passed." if not failures else f"\nFAILED: {failures}")
    finally:
        db.close_pool()