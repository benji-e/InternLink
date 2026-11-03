"""
handlers_profile.py - view and update the student's profile, skills, interests and CV.

Routes (all need a logged-in student):
    GET    /api/profile
    PUT    /api/profile
    POST   /api/profile/cv        (multipart/form-data, field name "cv")
    GET    /api/profile/cv
    DELETE /api/profile/cv
"""
import io
import re
import secrets
import zipfile
from pathlib import Path

from psycopg2 import errors as pg_errors

import auth_utils
import config
import db
from router import HttpError, Response, route

CV_MAX_BYTES = min(config.MAX_CV_BYTES, 5_242_880)       # the schema allows at most 5 MB
CV_MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
LOCKED_FIELDS = ("email", "student_number", "university_id", "department_id", "programme_id")
MAX_SKILLS = 30
MAX_INTERESTS = 20
_PHONE_RE = re.compile(r"^\+?[0-9][0-9 \-]{6,18}[0-9]$")


# ---------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------
def _text(value, label, max_len, required=False, min_len=1):
    """Clean a text field. Returns None when it is empty and not required."""
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


def _year(value):
    if isinstance(value, (bool, float)) or value is None:
        raise HttpError(400, "Year of study must be a number from 1 to 6.")
    try:
        year = int(value)
    except (TypeError, ValueError):
        raise HttpError(400, "Year of study must be a number from 1 to 6.")
    if not 1 <= year <= 6:
        raise HttpError(400, "Year of study must be a number from 1 to 6.")
    return year


def _id_list(value, label, max_items):
    """A JSON list of positive whole numbers, without duplicates."""
    if not isinstance(value, list):
        raise HttpError(400, f"{label} must be a list.")
    ids = []
    for item in value:
        if isinstance(item, (bool, float)) or not isinstance(item, int) or not 1 <= item <= 10 ** 18:
            raise HttpError(400, f"{label} contains an invalid value.")
        if item not in ids:
            ids.append(item)
    if len(ids) > max_items:
        raise HttpError(400, f"You can choose at most {max_items} {label.lower()}.")
    return ids


# ---------------------------------------------------------------------
# Reading the profile
# ---------------------------------------------------------------------
def load_profile(user_id):
    """Everything the profile page and dashboard need, in one dictionary."""
    row = db.fetch_one(
        """
        SELECT u.user_id, u.email, u.full_name, u.phone, u.created_at,
               sp.student_id, sp.student_number, sp.year_of_study,
               sp.preferred_location, sp.willing_to_relocate,
               sp.verified, sp.verified_at,
               sp.cv_path, sp.cv_size_bytes, sp.cv_uploaded_at,
               un.university_id, un.name AS university_name,
               d.department_id,  d.name  AS department_name,
               p.programme_id,   p.name  AS programme_name
        FROM users u
        JOIN student_profiles sp ON sp.user_id = u.user_id
        JOIN universities un     ON un.university_id = sp.university_id
        JOIN departments d       ON d.department_id = sp.department_id
        JOIN programmes p        ON p.programme_id = sp.programme_id
        WHERE u.user_id = %s AND u.role = 'student'
        """,
        (user_id,),
    )
    if row is None:
        raise HttpError(404, "Profile not found.")

    student_id = row["student_id"]
    skills = db.fetch_all(
        "SELECT s.skill_id, s.name FROM student_skills ss "
        "JOIN skills s ON s.skill_id = ss.skill_id WHERE ss.student_id = %s ORDER BY s.name",
        (student_id,),
    )
    interests = db.fetch_all(
        "SELECT i.interest_id, i.name FROM student_interests si "
        "JOIN interests i ON i.interest_id = si.interest_id WHERE si.student_id = %s ORDER BY i.name",
        (student_id,),
    )

    has_cv = row["cv_path"] is not None
    checklist = [
        ("Phone number", bool(row["phone"])),
        ("Preferred location", bool(row["preferred_location"])),
        ("CV", has_cv),
        ("At least one skill", len(skills) > 0),
        ("At least one interest", len(interests) > 0),
    ]
    missing = [label for label, done in checklist if not done]

    profile = {
        "user_id": row["user_id"],
        "student_id": student_id,
        "email": row["email"],
        "full_name": row["full_name"],
        "phone": row["phone"],
        "student_number": row["student_number"],
        "year_of_study": row["year_of_study"],
        "preferred_location": row["preferred_location"],
        "willing_to_relocate": row["willing_to_relocate"],
        "verified": row["verified"],
        "verified_at": row["verified_at"],
        "university": {"id": row["university_id"], "name": row["university_name"]},
        "department": {"id": row["department_id"], "name": row["department_name"]},
        "programme": {"id": row["programme_id"], "name": row["programme_name"]},
        "cv": {
            "has_cv": has_cv,
            "file_type": Path(row["cv_path"]).suffix.lstrip(".").lower() if has_cv else None,
            "size_bytes": row["cv_size_bytes"],
            "uploaded_at": row["cv_uploaded_at"],
        },
        "created_at": row["created_at"],
    }
    return {
        "profile": profile,
        "skills": skills,
        "interests": interests,
        "completeness": {
            "percent": round(100 * (len(checklist) - len(missing)) / len(checklist)),
            "missing": missing,
        },
    }


@route("GET", "/api/profile")
@auth_utils.student_required
def get_profile(req):
    return load_profile(req.user["user_id"])


# ---------------------------------------------------------------------
# Updating the profile
# ---------------------------------------------------------------------
@route("PUT", "/api/profile")
@auth_utils.student_required
def update_profile(req):
    body = req.json()
    user_id = req.user["user_id"]
    student_id = req.user["student_id"]

    locked = [name for name in LOCKED_FIELDS if name in body]
    if locked:
        raise HttpError(400, "Your email, student number, university, department and programme "
                             "cannot be changed here. Please contact your university coordinator.")

    user_updates = {}        # columns of users
    profile_updates = {}     # columns of student_profiles
    skill_ids = interest_ids = None

    if "full_name" in body:
        user_updates["full_name"] = _text(body["full_name"], "Full name", 100, required=True, min_len=2)
    if "phone" in body:
        phone = _text(body["phone"], "Phone number", 20)
        if phone and not _PHONE_RE.match(phone):
            raise HttpError(400, "Phone number is not valid. Example: +256 700 000000")
        user_updates["phone"] = phone
    if "year_of_study" in body:
        profile_updates["year_of_study"] = _year(body["year_of_study"])
    if "preferred_location" in body:
        profile_updates["preferred_location"] = _text(body["preferred_location"], "Preferred location", 100)
    if "willing_to_relocate" in body:
        if not isinstance(body["willing_to_relocate"], bool):
            raise HttpError(400, "Willing to relocate must be true or false.")
        profile_updates["willing_to_relocate"] = body["willing_to_relocate"]
    if "skill_ids" in body:
        skill_ids = _id_list(body["skill_ids"], "Skills", MAX_SKILLS)
    if "interest_ids" in body:
        interest_ids = _id_list(body["interest_ids"], "Interests", MAX_INTERESTS)

    if not (user_updates or profile_updates or skill_ids is not None or interest_ids is not None):
        raise HttpError(400, "There is nothing to update.")

    try:
        with db.transaction(user_id=user_id) as cur:
            if user_updates:
                # column names come from the fixed keys above, never from user input
                assignments = ", ".join(f"{col} = %s" for col in user_updates)
                cur.execute(f"UPDATE users SET {assignments}, updated_at = now() WHERE user_id = %s",
                            (*user_updates.values(), user_id))
            if profile_updates:
                assignments = ", ".join(f"{col} = %s" for col in profile_updates)
                cur.execute(f"UPDATE student_profiles SET {assignments}, updated_at = now() WHERE student_id = %s",
                            (*profile_updates.values(), student_id))

            if skill_ids is not None:
                cur.execute("SELECT count(*) AS n FROM skills WHERE skill_id = ANY(%s::bigint[])", (skill_ids,))
                if cur.fetchone()["n"] != len(skill_ids):
                    raise HttpError(400, "One of the chosen skills does not exist.")
                cur.execute("DELETE FROM student_skills WHERE student_id = %s", (student_id,))
                if skill_ids:
                    cur.execute("INSERT INTO student_skills (student_id, skill_id) "
                                "SELECT %s, unnest(%s::bigint[])", (student_id, skill_ids))

            if interest_ids is not None:
                cur.execute("SELECT count(*) AS n FROM interests WHERE interest_id = ANY(%s::bigint[])", (interest_ids,))
                if cur.fetchone()["n"] != len(interest_ids):
                    raise HttpError(400, "One of the chosen interests does not exist.")
                cur.execute("DELETE FROM student_interests WHERE student_id = %s", (student_id,))
                if interest_ids:
                    cur.execute("INSERT INTO student_interests (student_id, interest_id) "
                                "SELECT %s, unnest(%s::bigint[])", (student_id, interest_ids))
    except pg_errors.RaiseException as exc:                  # message raised on purpose by a trigger
        raise HttpError(400, (exc.diag.message_primary or "The update was not accepted.")[:200])
    except (pg_errors.CheckViolation, pg_errors.ForeignKeyViolation):
        raise HttpError(400, "Some of the details were not accepted. Please check them and try again.")

    changed = sorted(list(user_updates) + list(profile_updates)
                     + (["skills"] if skill_ids is not None else [])
                     + (["interests"] if interest_ids is not None else []))
    auth_utils.audit("profile_updated", user_id, "student", req.client_ip,
                     "student_profiles", student_id, details={"fields": changed})

    result = load_profile(user_id)
    result["message"] = "Profile updated."
    return result


# ---------------------------------------------------------------------
# CV upload, download, delete
# ---------------------------------------------------------------------
def _validate_cv(filename, content):
    """Return the file extension (.pdf or .docx) or raise 400."""
    ext = Path(filename or "").suffix.lower()
    if ext not in config.ALLOWED_CV_EXTENSIONS:
        raise HttpError(400, "Only PDF or DOCX files are accepted.")
    if len(content) == 0:
        raise HttpError(400, "The file is empty.")
    if len(content) > CV_MAX_BYTES:
        raise HttpError(400, f"The file is too large. The maximum size is {CV_MAX_BYTES // (1024 * 1024)} MB.")

    if ext == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise HttpError(400, "This file is not a real PDF.")
    else:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = set(archive.namelist())
            real_docx = "[Content_Types].xml" in names and "word/document.xml" in names
        except zipfile.BadZipFile:
            real_docx = False
        if not real_docx:
            raise HttpError(400, "This file is not a real Word (.docx) document.")
    return ext


def _cv_file(stored_name):
    """Path of a stored CV inside the upload folder, or None if it is missing."""
    base = config.UPLOAD_DIR.resolve()
    path = (base / Path(stored_name).name).resolve()
    if path.parent == base and path.is_file():
        return path
    return None


def _remove_file(stored_name):
    if not stored_name:
        return
    try:
        path = _cv_file(stored_name)
        if path:
            path.unlink()
    except OSError:
        print("WARNING: could not delete old CV file", stored_name)


@route("POST", "/api/profile/cv")
@auth_utils.student_required
def upload_cv(req):
    user_id = req.user["user_id"]
    student_id = req.user["student_id"]
    auth_utils.check_rate_limit(f"cv:{user_id}", 20, 3600)

    _, files = req.multipart()
    upload = files.get("cv")
    if not upload:
        raise HttpError(400, "Please choose a CV file to upload.")
    content = upload["content"]
    ext = _validate_cv(upload["filename"], content)

    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = f"student_{student_id}_{secrets.token_hex(8)}{ext}"      # random, no user text
    (config.UPLOAD_DIR / stored_name).write_bytes(content)

    old_name = None
    try:
        with db.transaction(user_id=user_id) as cur:
            cur.execute("SELECT cv_path FROM student_profiles WHERE student_id = %s FOR UPDATE", (student_id,))
            old = cur.fetchone()
            old_name = old["cv_path"] if old else None
            cur.execute(
                "UPDATE student_profiles SET cv_path = %s, cv_size_bytes = %s, "
                "cv_uploaded_at = now(), updated_at = now() WHERE student_id = %s",
                (stored_name, len(content), student_id),
            )
    except Exception:
        _remove_file(stored_name)                    # do not leave an orphan file behind
        raise
    _remove_file(old_name)

    auth_utils.audit("cv_uploaded", user_id, "student", req.client_ip, "student_profiles", student_id,
                     details={"type": ext.lstrip("."), "size_bytes": len(content)})
    result = load_profile(user_id)
    result["message"] = "CV uploaded."
    return result


@route("GET", "/api/profile/cv")
@auth_utils.student_required
def download_cv(req):
    row = db.fetch_one("SELECT cv_path, student_number FROM student_profiles WHERE student_id = %s",
                       (req.user["student_id"],))
    if not row or not row["cv_path"]:
        raise HttpError(404, "You have not uploaded a CV yet.")
    path = _cv_file(row["cv_path"])
    if path is None:
        raise HttpError(404, "Your CV file could not be found. Please upload it again.")
    ext = path.suffix.lower()
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", row["student_number"]).strip("_") or "student"
    return Response(path.read_bytes(), 200, CV_MIME[ext],
                    headers=[("Content-Disposition", f'attachment; filename="CV_{safe_name}{ext}"')])


@route("DELETE", "/api/profile/cv")
@auth_utils.student_required
def delete_cv(req):
    user_id = req.user["user_id"]
    student_id = req.user["student_id"]
    with db.transaction(user_id=user_id) as cur:
        cur.execute("SELECT cv_path FROM student_profiles WHERE student_id = %s FOR UPDATE", (student_id,))
        old = cur.fetchone()
        old_name = old["cv_path"] if old else None
        if not old_name:
            raise HttpError(404, "You have not uploaded a CV.")
        cur.execute(
            "UPDATE student_profiles SET cv_path = NULL, cv_size_bytes = NULL, "
            "cv_uploaded_at = NULL, updated_at = now() WHERE student_id = %s",
            (student_id,),
        )
    _remove_file(old_name)
    auth_utils.audit("cv_deleted", user_id, "student", req.client_ip, "student_profiles", student_id)
    result = load_profile(user_id)
    result["message"] = "CV removed."
    return result


# ---------------------------------------------------------------------
# Self-test:  python handlers_profile.py
# Uses the test account created by handlers_auth.py (email starts with "test.").
# It changes that test account's profile; real accounts are never touched.
# ---------------------------------------------------------------------
if __name__ == "__main__":
    import json

    from router import Request, router

    def call(method, path, body=None, cookie=None, raw=None, content_type="application/json"):
        headers = {"X-Requested-With": "InternLink"}
        if cookie:
            headers["Cookie"] = f"{config.SESSION_COOKIE}={cookie}"
        if raw is None and body is not None:
            raw = json.dumps(body).encode("utf-8")
        if raw is not None:
            headers["Content-Type"] = content_type
        return router.dispatch(Request(method, path, headers, raw or b"", "127.0.0.1"))

    def as_json(resp):
        return json.loads(resp.body) if resp.body else {}

    def multipart(filename, content):
        boundary = "----InternLinkTest" + secrets.token_hex(6)
        head = (f'--{boundary}\r\nContent-Disposition: form-data; name="cv"; filename="{filename}"\r\n'
                f"Content-Type: application/octet-stream\r\n\r\n").encode()
        tail = f"\r\n--{boundary}--\r\n".encode()
        return head + content + tail, f"multipart/form-data; boundary={boundary}"

    def make_docx():
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", "<document/>")
        return buffer.getvalue()

    failures = []

    def check(label, got, expected):
        good = got == expected
        if not good:
            failures.append(label)
        print(f"{'OK  ' if good else 'FAIL'} {label:<42} {got}" + ("" if good else f"  (expected {expected})"))

    try:
        student = db.fetch_one(
            "SELECT u.user_id, sp.student_id FROM users u JOIN student_profiles sp ON sp.user_id = u.user_id "
            "WHERE u.role = 'student' AND u.status = 'active' AND left(u.email, 5) = 'test.' "
            "ORDER BY u.user_id LIMIT 1"
        )
        if student is None:
            print("No test student account found. Run  python handlers_auth.py  first, then run this again.")
            raise SystemExit(1)
        cookie = auth_utils.create_session(student["user_id"])
        files_on_disk = lambda: len(list(config.UPLOAD_DIR.glob(f"student_{student['student_id']}_*"))) \
            if config.UPLOAD_DIR.exists() else 0

        check("profile without logging in", call("GET", "/api/profile").status, 401)
        resp = call("GET", "/api/profile", cookie=cookie)
        check("read profile", resp.status, 200)
        check("no CV yet", as_json(resp)["profile"]["cv"]["has_cv"], False)

        check("year 9 is rejected", call("PUT", "/api/profile", {"year_of_study": 9}, cookie).status, 400)
        check("locked field is rejected", call("PUT", "/api/profile", {"programme_id": 1}, cookie).status, 400)
        check("empty update is rejected", call("PUT", "/api/profile", {"unknown": 1}, cookie).status, 400)

        resp = call("PUT", "/api/profile", {"full_name": "Test Student Updated", "phone": "+256 700 123456",
                                            "year_of_study": 3, "preferred_location": "Kampala",
                                            "willing_to_relocate": True}, cookie)
        check("update basic details", resp.status, 200)
        p = as_json(resp)["profile"]
        check("details were saved",
              (p["full_name"], p["year_of_study"], p["preferred_location"], p["willing_to_relocate"]),
              ("Test Student Updated", 3, "Kampala", True))

        skills = db.fetch_all("SELECT skill_id FROM skills ORDER BY skill_id LIMIT 2")
        interests = db.fetch_all("SELECT interest_id FROM interests ORDER BY interest_id LIMIT 2")
        if skills and interests:
            check("unknown skill id is rejected",
                  call("PUT", "/api/profile", {"skill_ids": [999999999]}, cookie).status, 400)
            resp = call("PUT", "/api/profile", {"skill_ids": [s["skill_id"] for s in skills],
                                                "interest_ids": [i["interest_id"] for i in interests]}, cookie)
            check("save skills and interests", resp.status, 200)
            data = as_json(resp)
            check("skills and interests were saved", (len(data["skills"]), len(data["interests"])),
                  (len(skills), len(interests)))
        else:
            print("SKIP skills/interests checks (the skills or interests table is empty)")

        resp = call("PUT", "/api/profile", {"preferred_location": ""}, cookie)
        check("clear preferred location", as_json(resp)["profile"]["preferred_location"], None)

        body, ctype = multipart("cv.pdf", b"this is not a pdf")
        check("fake PDF is rejected", call("POST", "/api/profile/cv", cookie=cookie, raw=body, content_type=ctype).status, 400)
        body, ctype = multipart("virus.exe", b"%PDF-1.4 fake")
        check("an .exe file is rejected", call("POST", "/api/profile/cv", cookie=cookie, raw=body, content_type=ctype).status, 400)

        pdf_bytes = b"%PDF-1.4\n% InternLink test file\n"
        body, ctype = multipart("my cv.pdf", pdf_bytes)
        resp = call("POST", "/api/profile/cv", cookie=cookie, raw=body, content_type=ctype)
        check("upload a PDF", resp.status, 200)
        check("profile now shows a CV", as_json(resp)["profile"]["cv"]["has_cv"], True)

        resp = call("GET", "/api/profile/cv", cookie=cookie)
        check("download returns the same bytes", (resp.status, resp.body == pdf_bytes), (200, True))

        body, ctype = multipart("cv.docx", make_docx())
        check("upload a DOCX (replaces the PDF)", call("POST", "/api/profile/cv", cookie=cookie, raw=body, content_type=ctype).status, 200)
        check("only one CV file is on disk", files_on_disk(), 1)

        check("delete the CV", call("DELETE", "/api/profile/cv", cookie=cookie).status, 200)
        check("no CV files left on disk", files_on_disk(), 0)
        check("download after delete", call("GET", "/api/profile/cv", cookie=cookie).status, 404)

        print("\nAll checks passed." if not failures else f"\nFAILED: {failures}")
    finally:
        db.close_pool()