"""
handlers_meta.py - read-only lists for dropdowns and filters.

Routes:
    GET /api/meta/universities                      (public)
    GET /api/meta/departments?university_id=1       (public)
    GET /api/meta/programmes?department_id=1        (public)
    GET /api/meta/skills[?q=py]                     (student)
    GET /api/meta/interests                         (student)
    GET /api/meta/listing-filters                   (student)
"""
import auth_utils
import db
import recommend
from router import HttpError, route


def _id_param(req, name, label):
    """Read a positive integer from the query string or answer 400."""
    raw = req.query.get(name, "")
    if not raw.isdigit() or not 1 <= int(raw) <= 10 ** 18:
        raise HttpError(400, f"Please choose a valid {label}.")
    return int(raw)


def _public_limit(req):
    auth_utils.check_rate_limit(f"meta:{req.client_ip}", 120, 60)


# ---------------------------------------------------------------------
# Public lists for the sign-up form
# ---------------------------------------------------------------------
@route("GET", "/api/meta/universities")
def list_universities(req):
    _public_limit(req)
    rows = db.fetch_all(
        """
        SELECT university_id, name, location, email_domain
        FROM universities
        WHERE status = 'verified'
        ORDER BY name
        """
    )
    return {"universities": rows}


@route("GET", "/api/meta/departments")
def list_departments(req):
    _public_limit(req)
    university_id = _id_param(req, "university_id", "university")
    rows = db.fetch_all(
        """
        SELECT d.department_id, d.name
        FROM departments d
        JOIN universities u ON u.university_id = d.university_id
        WHERE d.university_id = %s AND u.status = 'verified'
        ORDER BY d.name
        """,
        (university_id,),
    )
    return {"departments": rows}


@route("GET", "/api/meta/programmes")
def list_programmes(req):
    _public_limit(req)
    department_id = _id_param(req, "department_id", "department")
    rows = db.fetch_all(
        """
        SELECT p.programme_id, p.name, p.programme_group
        FROM programmes p
        JOIN departments d ON d.department_id = p.department_id
        JOIN universities u ON u.university_id = d.university_id
        WHERE p.department_id = %s AND u.status = 'verified'
        ORDER BY p.name
        """,
        (department_id,),
    )
    return {"programmes": rows}


# ---------------------------------------------------------------------
# Lists for logged-in students
# ---------------------------------------------------------------------
@route("GET", "/api/meta/skills")
@auth_utils.student_required
def list_skills(req):
    q = (req.query.get("q") or "").strip().lower()[:50]
    if q:
        # escape LIKE wildcards so a typed % or _ is treated as a normal character
        pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = db.fetch_all(
            "SELECT skill_id, name FROM skills WHERE lower(name) LIKE %s ORDER BY name LIMIT 100",
            (pattern,),
        )
    else:
        rows = db.fetch_all("SELECT skill_id, name FROM skills ORDER BY name LIMIT 1000")
    return {"skills": rows}


@route("GET", "/api/meta/interests")
@auth_utils.student_required
def list_interests(req):
    rows = db.fetch_all("SELECT interest_id, name FROM interests ORDER BY name LIMIT 1000")
    return {"interests": rows}


@route("GET", "/api/meta/listing-filters")
@auth_utils.student_required
def listing_filters(req):
    """Sectors, locations and durations that exist on listings the student can currently apply to."""
    base = (
        "FROM listings l JOIN companies c ON c.company_id = l.company_id WHERE "
        + recommend.OPEN_LISTING_WHERE
    )
    sectors = db.fetch_all(f"SELECT min(l.sector) AS value {base} GROUP BY lower(l.sector) ORDER BY lower(min(l.sector))")
    locations = db.fetch_all(f"SELECT min(l.location) AS value {base} GROUP BY lower(l.location) ORDER BY lower(min(l.location))")
    duration = db.fetch_one(f"SELECT min(l.duration_weeks) AS min_weeks, max(l.duration_weeks) AS max_weeks {base}")
    return {
        "sectors": [r["value"] for r in sectors],
        "locations": [r["value"] for r in locations],
        "duration_weeks": {"min": duration["min_weeks"], "max": duration["max_weeks"]},
    }


# ---------------------------------------------------------------------
# Self-test:  python handlers_meta.py      (reads only, writes nothing)
# ---------------------------------------------------------------------
if __name__ == "__main__":
    import json

    import config
    from router import Request, router

    def call(path, cookie=None):
        headers = {}
        if cookie:
            headers["Cookie"] = f"{config.SESSION_COOKIE}={cookie}"
        resp = router.dispatch(Request("GET", path, headers, b"", "127.0.0.1"))
        return resp.status, json.loads(resp.body)

    failures = []

    def check(label, got, expected):
        good = got == expected
        if not good:
            failures.append(label)
        print(f"{'OK  ' if good else 'FAIL'} {label:<46} {got}" + ("" if good else f"  (expected {expected})"))

    try:
        status, data = call("/api/meta/universities")
        check("universities (public)", status, 200)
        unis = data["universities"]
        print(f"     {len(unis)} verified universities")
        if not unis:
            print("     WARNING: none are verified, so nobody can sign up. Fix the seed data first.")

        status, data = call("/api/meta/departments?university_id=" + (str(unis[0]["university_id"]) if unis else "1"))
        check("departments of the first university", status, 200)
        depts = data["departments"]
        print(f"     {len(depts)} departments")

        status, data = call("/api/meta/programmes?department_id=" + (str(depts[0]["department_id"]) if depts else "1"))
        check("programmes of the first department", status, 200)
        print(f"     {len(data['programmes'])} programmes")

        status, _ = call("/api/meta/departments")
        check("departments without university_id", status, 400)
        status, _ = call("/api/meta/programmes?department_id=abc")
        check("programmes with a bad department_id", status, 400)
        status, _ = call("/api/meta/skills")
        check("skills without logging in", status, 401)

        student = db.fetch_one(
            "SELECT u.user_id FROM users u JOIN student_profiles sp ON sp.user_id = u.user_id "
            "WHERE u.role = 'student' AND u.status = 'active' ORDER BY u.user_id LIMIT 1"
        )
        if student is None:
            print("\nNo active student account exists yet, so the logged-in checks are skipped.")
            print("Run  python handlers_auth.py  first, then run this test again.")
        else:
            cookie = auth_utils.create_session(student["user_id"])      # in-memory only, nothing is written
            status, data = call("/api/meta/skills", cookie)
            check("skills (logged in)", status, 200)
            print(f"     {len(data['skills'])} skills")
            status, data = call("/api/meta/skills?q=%25", cookie)
            check("skills search with a % character", status, 200)
            status, data = call("/api/meta/interests", cookie)
            check("interests (logged in)", status, 200)
            print(f"     {len(data['interests'])} interests")
            status, data = call("/api/meta/listing-filters", cookie)
            check("listing filters (logged in)", status, 200)
            print(f"     {len(data['sectors'])} sectors, {len(data['locations'])} locations, "
                  f"durations {data['duration_weeks']}")

        print("\nAll checks passed." if not failures else f"\nFAILED: {failures}")
    finally:
        db.close_pool()