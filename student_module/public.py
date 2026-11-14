"""Pages anyone can see without signing in: home page, internship search and
internship details. A signed-in student also gets their match score."""

from __future__ import annotations

import re
from typing import Any

from psycopg.rows import dict_row

from .service import EMAIL_RE, StudentError

SORTS = {
    "closing": "v.application_deadline, v.listing_id",
    "newest": "v.posted_at DESC, v.listing_id DESC",
}
# Match bars on the detail page use the weights in fn_recommendations.
MATCH_WEIGHTS = {"skills": 40, "programme": 35, "interests": 15, "location": 10}

LISTING_COLUMNS = """
    v.listing_id, v.title, v.company_name, v.sector, v.location, v.is_remote,
    v.duration_weeks, v.slots_remaining, v.application_deadline, v.posted_at,
    v.required_skills
"""


def _int(value: Any, label: str, *, low: int, high: int, default: int | None = None) -> int | None:
    if value in (None, ""):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise StudentError(422, "INVALID_FILTER", f"Check the {label} filter.") from None
    if not low <= number <= high:
        raise StudentError(422, "INVALID_FILTER", f"Check the {label} filter.")
    return number


def search_opportunities(conn, filters: dict[str, str], student_id: int | None = None) -> dict:
    """Open internships matching the filters, with sector counts for the filter panel."""
    search = (filters.get("q") or filters.get("search") or "").strip()[:120]
    sector = (filters.get("sector") or "").strip()[:80]
    location = (filters.get("location") or "").strip()[:80]
    remote = filters.get("remote", "")
    closing_soon = filters.get("closing_soon", "") == "true"
    my_programme = filters.get("my_programme", "") == "true"
    sort = filters.get("sort") or "closing"
    if sort not in SORTS:
        raise StudentError(422, "INVALID_FILTER", "Check the sort order.")
    if remote not in ("", "true", "false"):
        raise StudentError(422, "INVALID_FILTER", "Check the remote filter.")
    min_weeks = _int(filters.get("min_weeks"), "duration", low=1, high=52)
    max_weeks = _int(filters.get("max_weeks"), "duration", low=1, high=52)
    page = _int(filters.get("page"), "page", low=1, high=10_000, default=1)
    page_size = _int(filters.get("page_size"), "page size", low=1, high=50, default=10)

    clauses: list[str] = []
    params: list[Any] = []
    if search:
        clauses.append("(v.search_vector @@ websearch_to_tsquery('english', %s) OR v.company_name ILIKE %s)")
        params += [search, f"%{search}%"]
    if location:
        clauses.append("v.location ILIKE %s")
        params.append(f"%{location}%")
    if remote:
        clauses.append("v.is_remote = %s")
        params.append(remote == "true")
    if min_weeks is not None:
        clauses.append("v.duration_weeks >= %s")
        params.append(min_weeks)
    if max_weeks is not None:
        clauses.append("v.duration_weeks <= %s")
        params.append(max_weeks)
    if closing_soon:
        clauses.append("v.application_deadline <= CURRENT_DATE + 7")
    if my_programme and student_id is not None:
        clauses.append(
            "EXISTS (SELECT 1 FROM listing_programmes lp JOIN student_profiles sp "
            "ON sp.programme_id = lp.programme_id WHERE lp.listing_id = v.listing_id AND sp.student_id = %s)"
        )
        params.append(student_id)
    # Sector counts ignore the sector filter itself, so other sectors stay selectable.
    base_where = " AND ".join(clauses) or "TRUE"
    where = base_where + (" AND v.sector ILIKE %s" if sector else "")
    where_params = params + ([sector] if sector else [])

    with conn.cursor(row_factory=dict_row) as cur:
        sectors = cur.execute(
            f"SELECT v.sector AS name, count(*) AS count FROM v_open_listings v WHERE {base_where} "
            "GROUP BY v.sector ORDER BY count(*) DESC, v.sector",
            params,
        ).fetchall()
        count = cur.execute(f"SELECT count(*) AS n FROM v_open_listings v WHERE {where}", where_params).fetchone()["n"]
        rows = cur.execute(
            f"""
            SELECT {LISTING_COLUMNS}, a.status AS application_status,
                   EXISTS (SELECT 1 FROM saved_listings sl WHERE sl.listing_id = v.listing_id AND sl.student_id = %s) AS saved
            FROM v_open_listings v
            LEFT JOIN applications a ON a.listing_id = v.listing_id AND a.student_id = %s
            WHERE {where}
            ORDER BY {SORTS[sort]}
            LIMIT %s OFFSET %s
            """,
            [student_id, student_id, *where_params, page_size, (page - 1) * page_size],
        ).fetchall()
    return {"results": rows, "count": int(count), "page": page, "page_size": page_size, "sectors": sectors}


def home(conn, student_id: int | None = None) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        latest = cur.execute(
            f"""
            SELECT {LISTING_COLUMNS},
                   EXISTS (SELECT 1 FROM saved_listings sl WHERE sl.listing_id = v.listing_id AND sl.student_id = %s) AS saved
            FROM v_open_listings v ORDER BY v.posted_at DESC, v.listing_id DESC LIMIT 4
            """,
            (student_id,),
        ).fetchall()
        universities = cur.execute(
            "SELECT name FROM universities WHERE status = 'verified' ORDER BY name LIMIT 8"
        ).fetchall()
        locations = cur.execute(
            "SELECT DISTINCT location FROM v_open_listings ORDER BY location"
        ).fetchall()
    return {
        "latest": latest,
        "universities": [row["name"] for row in universities],
        "locations": [row["location"] for row in locations],
    }


MATCH_SQL = """
    SELECT r.score, r.p, r.s, r.i, r.l
    FROM fn_recommendations(%(sid)s, 100000, 0) r
    WHERE r.listing_id = %(lid)s
"""


def _match(cur, listing_id: int, student_id: int) -> dict | None:
    row = cur.execute(MATCH_SQL, {"sid": student_id, "lid": listing_id}).fetchone()
    if row is None:
        return None
    skills = cur.execute(
        """
        SELECT s.name, (ss.skill_id IS NOT NULL) AS has
        FROM listing_skills ls JOIN skills s ON s.skill_id = ls.skill_id
        LEFT JOIN student_skills ss ON ss.skill_id = ls.skill_id AND ss.student_id = %s
        WHERE ls.listing_id = %s ORDER BY ls.is_required DESC, s.name
        """,
        (student_id, listing_id),
    ).fetchall()

    def part(value):
        return None if value is None else round(float(value), 3)

    return {
        "score": int(row["score"]),
        "breakdown": {"skills": part(row["s"]), "programme": part(row["p"]),
                      "interests": part(row["i"]), "location": part(row["l"])},
        "weights": MATCH_WEIGHTS,
        "matched_skills": [item["name"] for item in skills if item["has"]],
        "missing_skills": [item["name"] for item in skills if not item["has"]],
    }


def opportunity_detail(conn, listing_id: int, student_id: int | None = None) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        listing = cur.execute(
            """
            SELECT v.listing_id, v.title, v.description, v.sector, v.location, v.is_remote,
                   v.duration_weeks, v.slots, v.slots_remaining, v.application_deadline, v.posted_at,
                   v.required_skills, v.accepted_programmes,
                   (v.application_deadline - CURRENT_DATE) AS days_left,
                   c.company_id, c.name AS company_name, c.description AS company_description,
                   c.location AS company_location, c.website AS company_website
            FROM v_open_listings v JOIN companies c ON c.company_id = v.company_id
            WHERE v.listing_id = %s
            """,
            (listing_id,),
        ).fetchone()
        if listing is None:
            raise StudentError(404, "LISTING_NOT_FOUND", "This internship is closed or no longer available.")
        listing["optional_skills"] = [row["name"] for row in cur.execute(
            "SELECT s.name FROM listing_skills ls JOIN skills s ON s.skill_id = ls.skill_id "
            "WHERE ls.listing_id = %s AND NOT ls.is_required ORDER BY s.name",
            (listing_id,),
        ).fetchall()]
        listing["similar"] = cur.execute(
            """
            SELECT v.listing_id, v.title, v.company_name FROM v_open_listings v
            WHERE v.listing_id <> %s AND (v.sector = %s OR v.company_id = %s)
            ORDER BY (v.sector = %s) DESC, v.application_deadline LIMIT 3
            """,
            (listing_id, listing["sector"], listing["company_id"], listing["sector"]),
        ).fetchall()
        listing["company_open_listings"] = cur.execute(
            "SELECT count(*) AS n FROM v_open_listings WHERE company_id = %s", (listing["company_id"],)
        ).fetchone()["n"]
        listing["match"] = None
        listing["application"] = None
        listing["saved"] = False
        if student_id is not None:
            listing["match"] = _match(cur, listing_id, student_id)
            listing["saved"] = cur.execute(
                "SELECT 1 FROM saved_listings WHERE listing_id = %s AND student_id = %s", (listing_id, student_id)
            ).fetchone() is not None
            listing["application"] = cur.execute(
                "SELECT application_id, status, submitted_at FROM applications WHERE listing_id = %s AND student_id = %s",
                (listing_id, student_id),
            ).fetchone()
    return listing


def university_programmes(conn, university_id: int) -> list[dict]:
    """Every programme at a verified university with its department, for a single sign-up dropdown."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """
            SELECT p.programme_id AS id, p.name, d.department_id, d.name AS department
            FROM programmes p
            JOIN departments d ON d.department_id = p.department_id
            JOIN universities u ON u.university_id = d.university_id
            WHERE u.university_id = %s AND u.status = 'verified'
            ORDER BY d.name, p.name
            """,
            (university_id,),
        ).fetchall()


_NAME_RE = re.compile(r"\S")


def request_university(conn, payload: dict) -> dict:
    """A student asks for a university that isn't on InternLink yet."""
    name = payload.get("university_name")
    if not isinstance(name, str) or not _NAME_RE.search(name):
        raise StudentError(422, "INVALID_INPUT", "Enter the university's name.")
    name = " ".join(name.split())
    if len(name) > 160:
        raise StudentError(422, "INVALID_INPUT", "The university name is too long.")
    emails = {}
    for key, label in (("requester_email", "Your email"), ("coordinator_email", "Coordinator's email")):
        value = payload.get(key)
        value = value.strip().lower() if isinstance(value, str) else ""
        if key == "requester_email" and not value:
            raise StudentError(422, "INVALID_INPUT", "Enter your email so we can tell you when it's added.")
        if value and (len(value) > 254 or not EMAIL_RE.fullmatch(value)):
            raise StudentError(422, "INVALID_EMAIL", f"{label} doesn't look like an email address.")
        emails[key] = value or None
    with conn.cursor(row_factory=dict_row) as cur:
        existing = cur.execute(
            "SELECT 1 FROM universities WHERE lower(name) = lower(%s) AND status = 'verified'", (name,)
        ).fetchone()
        if existing:
            raise StudentError(409, "ALREADY_LISTED", f"{name} is already on InternLink. Choose it from the list.")
        cur.execute(
            """
            INSERT INTO university_requests (university_name, requester_email, coordinator_email)
            VALUES (%s, %s, %s)
            ON CONFLICT (lower(university_name), requester_email) DO NOTHING
            """,
            (name, emails["requester_email"], emails["coordinator_email"]),
        )
    return {"message": f"Thanks. We'll email you when {name} joins InternLink."}
