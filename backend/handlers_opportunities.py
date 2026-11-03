"""
handlers_opportunities.py - find opportunities, view one, apply, recommendations.

Routes (all need a logged-in student):
    GET  /api/opportunities
    GET  /api/opportunities/<id>
    POST /api/opportunities/<id>/apply
    GET  /api/recommendations
"""
from datetime import date

from psycopg2 import errors as pg_errors

import auth_utils
import db
import recommend
from router import HttpError, route

SORTS = ("best_match", "deadline", "newest")
PER_PAGE_DEFAULT = 10
PER_PAGE_MAX = 50
MAX_COVER_NOTE = 2000


# ---------------------------------------------------------------------
# Query-string helpers
# ---------------------------------------------------------------------
def _query_text(req, name, max_len=100):
    value = (req.query.get(name) or "").strip()
    if len(value) > max_len:
        raise HttpError(400, f"'{name}' is too long.")
    return value


def _query_int(req, name, low, high):
    raw = (req.query.get(name) or "").strip()
    if not raw:
        return None
    if not (raw.isascii() and raw.isdigit()) or not low <= int(raw) <= high:
        raise HttpError(400, f"'{name}' must be a number from {low} to {high}.")
    return int(raw)


def _query_flag(req, name):
    return (req.query.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------
# Shaping listings for the frontend
# ---------------------------------------------------------------------
def _shape(listing, full=False):
    deadline = listing["application_deadline"]
    description = listing.get("description") or ""
    item = {
        "listing_id": listing["listing_id"],
        "title": listing["title"],
        "company_name": listing["company_name"],
        "sector": listing["sector"],
        "location": listing["location"],
        "is_remote": listing["is_remote"],
        "duration_weeks": listing["duration_weeks"],
        "slots_available": listing["slots"] - listing["slots_filled"],
        "application_deadline": deadline,
        "days_left": (deadline - date.today()).days if deadline else None,
        "posted_at": listing.get("posted_at"),
        "status": listing["status"],
        "already_applied": listing["already_applied"],
        "skills": [{"name": s["name"], "required": s["required"]} for s in listing["skills"]],
        "programmes": [p["name"] for p in listing["programmes"]],
        "interests": listing["interests"],
        "match_score": listing.get("match_score"),
        "match_breakdown": listing.get("match_breakdown"),
        "matched_skills": listing.get("matched_skills", []),
        "missing_skills": listing.get("missing_skills", []),
    }
    if full:
        item["description"] = description
    else:
        item["description_preview"] = description[:200] + ("..." if len(description) > 200 else "")
    return item


def _is_open(listing_id):
    """True if students may currently apply to this listing."""
    row = db.fetch_one(
        "SELECT EXISTS (SELECT 1 FROM listings l JOIN companies c ON c.company_id = l.company_id "
        "WHERE l.listing_id = %s AND " + recommend.OPEN_LISTING_WHERE + ") AS is_open",
        (listing_id,),
    )
    return bool(row and row["is_open"])


# ---------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------
@route("GET", "/api/opportunities")
@auth_utils.student_required
def search_opportunities(req):
    student_id = req.user["student_id"]

    conditions, params = [], []
    q = _query_text(req, "q")
    if q:
        conditions.append("l.search_vector @@ websearch_to_tsquery('english', %s)")
        params.append(q)
    sector = _query_text(req, "sector")
    if sector:
        conditions.append("lower(l.sector) = lower(%s)")
        params.append(sector)
    location = _query_text(req, "location")
    if location:
        conditions.append("lower(l.location) = lower(%s)")
        params.append(location)
    if _query_flag(req, "remote"):
        conditions.append("l.is_remote")
    max_weeks = _query_int(req, "max_weeks", 1, 52)
    if max_weeks:
        conditions.append("l.duration_weeks <= %s")
        params.append(max_weeks)
    if _query_flag(req, "for_my_programme"):
        conditions.append("EXISTS (SELECT 1 FROM listing_programmes lp "
                          "WHERE lp.listing_id = l.listing_id AND lp.programme_id = %s)")
        params.append(req.user["programme_id"])
    if _query_flag(req, "hide_applied"):
        conditions.append("NOT EXISTS (SELECT 1 FROM applications a2 "
                          "WHERE a2.listing_id = l.listing_id AND a2.student_id = %s)")
        params.append(student_id)

    sort = (req.query.get("sort") or "best_match").strip().lower()
    if sort not in SORTS:
        raise HttpError(400, "Sort must be one of: " + ", ".join(SORTS) + ".")
    page = _query_int(req, "page", 1, 10000) or 1
    per_page = _query_int(req, "per_page", 1, PER_PAGE_MAX) or PER_PAGE_DEFAULT

    student = recommend.get_student_context(student_id)
    if student is None:
        raise HttpError(404, "Profile not found.")

    listings = recommend.fetch_open_listings(student_id, " AND ".join(conditions), tuple(params))
    for listing in listings:
        recommend.attach_score(student, listing)

    if sort == "best_match":
        listings.sort(key=lambda x: (-x["match_score"], x["application_deadline"], x["listing_id"]))
    elif sort == "deadline":
        listings.sort(key=lambda x: (x["application_deadline"], -x["match_score"], x["listing_id"]))
    else:  # newest first
        listings.sort(key=lambda x: (x["posted_at"].timestamp() if x["posted_at"] else 0, x["listing_id"]),
                      reverse=True)

    total = len(listings)
    pages = max(1, -(-total // per_page))
    start = (page - 1) * per_page
    return {
        "opportunities": [_shape(item) for item in listings[start:start + per_page]],
        "total": total,
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "profile_verified": req.user["verified"],
    }


# ---------------------------------------------------------------------
# One listing in full
# ---------------------------------------------------------------------
@route("GET", "/api/opportunities/<int:listing_id>")
@auth_utils.student_required
def get_opportunity(req):
    listing_id = req.params["listing_id"]
    student_id = req.user["student_id"]

    # A student can see open listings, and also listings they applied to (even after they close).
    where = ("l.listing_id = %s AND ((" + recommend.OPEN_LISTING_WHERE + ") OR EXISTS ("
             "SELECT 1 FROM applications a3 WHERE a3.listing_id = l.listing_id AND a3.student_id = %s))")
    rows = recommend.fetch_listings(student_id, where, (listing_id, student_id))
    if not rows:
        raise HttpError(404, "This opportunity was not found.")
    listing = rows[0]

    student = recommend.get_student_context(student_id)
    recommend.attach_score(student, listing)

    company = db.fetch_one(
        "SELECT sector, location, description, website FROM companies WHERE company_id = %s",
        (listing["company_id"],),
    )
    application = db.fetch_one(
        "SELECT application_id, status, submitted_at FROM applications "
        "WHERE student_id = %s AND listing_id = %s",
        (student_id, listing_id),
    )

    reason = None
    if application:
        reason = "You have already applied to this opportunity."
    elif not _is_open(listing_id):
        reason = "This opportunity is no longer accepting applications."
    elif not req.user["verified"]:
        reason = "Your profile must be verified by your university coordinator before you can apply."

    return {
        "opportunity": _shape(listing, full=True),
        "company": company,
        "application": application,
        "can_apply": reason is None,
        "cannot_apply_reason": reason,
    }


# ---------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------
@route("POST", "/api/opportunities/<int:listing_id>/apply")
@auth_utils.student_required
def apply_to_opportunity(req):
    listing_id = req.params["listing_id"]
    user_id = req.user["user_id"]
    student_id = req.user["student_id"]
    auth_utils.check_rate_limit(f"apply:{user_id}", 30, 3600)

    body = req.json() if req.raw_body else {}
    cover_note = body.get("cover_note")
    if cover_note is None:
        cover_note = ""
    if not isinstance(cover_note, str):
        raise HttpError(400, "Cover note must be text.")
    cover_note = cover_note.strip()
    if len(cover_note) > MAX_COVER_NOTE:
        raise HttpError(400, f"Cover note must be at most {MAX_COVER_NOTE} characters.")
    cover_note = cover_note or None

    if not req.user["verified"]:
        raise HttpError(403, "Your profile must be verified by your university coordinator before you can apply.")
    if not _is_open(listing_id):
        raise HttpError(404, "This opportunity is not open for applications. It may have closed, "
                             "its deadline may have passed, or all slots may be filled.")

    match_score = recommend.score_for_application(student_id, listing_id)

    try:
        with db.transaction(user_id=user_id) as cur:
            cur.execute(
                """
                INSERT INTO applications (student_id, listing_id, cover_note, match_score)
                VALUES (%s, %s, %s, %s)
                RETURNING application_id, status, match_score, submitted_at
                """,
                (student_id, listing_id, cover_note, match_score),
            )
            application = dict(cur.fetchone())
    except pg_errors.UniqueViolation:
        raise HttpError(409, "You have already applied to this opportunity.")
    except pg_errors.RaiseException as exc:                # a rule raised on purpose by a database trigger
        raise HttpError(400, (exc.diag.message_primary or "Your application was not accepted.")[:200])
    except (pg_errors.CheckViolation, pg_errors.ForeignKeyViolation):
        raise HttpError(400, "Your application was not accepted. Please check the details and try again.")

    auth_utils.audit("application_submitted", user_id, "student", req.client_ip,
                     "applications", application["application_id"],
                     details={"listing_id": listing_id})
    return {"message": "Application submitted.", "application": application}, 201


# ---------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------
@route("GET", "/api/recommendations")
@auth_utils.student_required
def get_recommendations(req):
    student_id = req.user["student_id"]
    limit = _query_int(req, "limit", 1, 50) or 10

    student = recommend.get_student_context(student_id)
    if student is None:
        raise HttpError(404, "Profile not found.")
    items = recommend.recommend_for_student(student_id, limit=limit)

    tips = []
    if not student["skill_ids"]:
        tips.append("Add your skills to your profile to get much better matches.")
    if not student["interest_names"]:
        tips.append("Add your interests to your profile so we can match them to listing sectors.")
    if not student["preferred_location"]:
        tips.append("Set a preferred location so location can count towards your matches.")

    return {
        "recommendations": [_shape(item) for item in items],
        "total": len(items),
        "tips": tips,
        "profile_verified": req.user["verified"],
    }


# ---------------------------------------------------------------------
# Self-test
#   python handlers_opportunities.py            read-only checks (nothing is changed)
#   python handlers_opportunities.py --apply    ALSO verifies the test account and submits one
#                                               application for it (this stays in the database)
# ---------------------------------------------------------------------
if __name__ == "__main__":
    import json
    import re
    import sys
    from urllib.parse import quote

    import config
    from router import Request, router

    def call(method, path, body=None, cookie=None):
        headers = {"X-Requested-With": "InternLink", "Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = f"{config.SESSION_COOKIE}={cookie}"
        raw = json.dumps(body).encode("utf-8") if body is not None else b""
        resp = router.dispatch(Request(method, path, headers, raw, "127.0.0.1"))
        return resp.status, (json.loads(resp.body) if resp.body else {})

    failures = []

    def check(label, got, expected):
        good = got == expected
        if not good:
            failures.append(label)
        print(f"{'OK  ' if good else 'FAIL'} {label:<48} {got}" + ("" if good else f"  (expected {expected})"))

    try:
        student = db.fetch_one(
            "SELECT u.user_id, sp.student_id, sp.verified FROM users u "
            "JOIN student_profiles sp ON sp.user_id = u.user_id "
            "WHERE u.role = 'student' AND u.status = 'active' AND left(u.email, 5) = 'test.' "
            "ORDER BY u.user_id LIMIT 1"
        )
        if student is None:
            print("No test student account found. Run  python handlers_auth.py  first, then run this again.")
            raise SystemExit(1)
        cookie = auth_utils.create_session(student["user_id"])

        check("search without logging in", call("GET", "/api/opportunities")[0], 401)
        check("bad sort value", call("GET", "/api/opportunities?sort=banana", cookie=cookie)[0], 400)
        check("bad max_weeks value", call("GET", "/api/opportunities?max_weeks=abc", cookie=cookie)[0], 400)
        check("quotes in the search box are safe",
              call("GET", "/api/opportunities?q=" + quote("'); drop table users; --"), cookie)[0], 200)

        status, data = call("GET", "/api/opportunities", cookie=cookie)
        check("list open opportunities", status, 200)
        total = data["total"]
        print(f"     {total} open opportunities")

        if total == 0:
            print("\nThere are no open listings, so the search/detail/apply checks are skipped.")
            print("Listings are created by employers (another module). Ask me for a small SQL test-data script.")
        else:
            first = data["opportunities"][0]
            lid = first["listing_id"]
            check("scores are between 0 and 100", all(0 <= o["match_score"] <= 100 for o in data["opportunities"]), True)
            scores = [o["match_score"] for o in data["opportunities"]]
            check("best_match sort is descending", scores == sorted(scores, reverse=True), True)

            _, dd = call("GET", "/api/opportunities?sort=deadline", cookie=cookie)
            deadlines = [o["application_deadline"] for o in dd["opportunities"]]
            check("deadline sort is ascending", deadlines == sorted(deadlines), True)

            _, one = call("GET", "/api/opportunities?per_page=1&page=1", cookie=cookie)
            check("pagination: one item per page", (len(one["opportunities"]), one["pages"]), (1, total))

            _, fs = call("GET", "/api/opportunities?sector=" + quote(first["sector"]), cookie=cookie)
            check("sector filter only returns that sector",
                  all(o["sector"].lower() == first["sector"].lower() for o in fs["opportunities"]), True)

            words = sorted(re.findall(r"[A-Za-z]{4,}", first["title"]), key=len, reverse=True)
            if words:
                _, qs = call("GET", "/api/opportunities?q=" + quote(words[0]), cookie=cookie)
                check(f"text search for '{words[0]}' finds the listing",
                      lid in [o["listing_id"] for o in qs["opportunities"]], True)

            status, detail = call("GET", f"/api/opportunities/{lid}", cookie=cookie)
            check("view one listing", status, 200)
            check("detail has the full description", "description" in detail["opportunity"], True)
            check("unknown listing gives 404", call("GET", "/api/opportunities/999999999", cookie=cookie)[0], 404)

        status, rec = call("GET", "/api/recommendations?limit=5", cookie=cookie)
        check("recommendations", status, 200)
        print(f"     {rec['total']} recommended; tips: {rec['tips']}")
        for item in rec["recommendations"][:3]:
            print(f"       {item['match_score']:>6}  {item['title']} ({item['company_name']})")

        me = db.fetch_one("SELECT verified FROM student_profiles WHERE student_id = %s", (student["student_id"],))
        if not me["verified"]:
            check("apply while NOT verified is refused", call("POST", "/api/opportunities/1/apply", {}, cookie)[0], 403)

        if "--apply" in sys.argv and total > 0:
            if not me["verified"]:
                try:
                    db.execute("UPDATE student_profiles SET verified = true, verified_at = now() "
                               "WHERE student_id = %s", (student["student_id"],))
                    print("     test account marked as verified")
                except Exception as exc:
                    print("SKIP apply tests: the database would not let me verify the test account:")
                    print("    ", str(exc).strip().splitlines()[0])
            me = db.fetch_one("SELECT verified FROM student_profiles WHERE student_id = %s", (student["student_id"],))
            if me["verified"]:
                _, cand = call("GET", "/api/opportunities?hide_applied=1&per_page=5", cookie=cookie)
                applied_id, last_error = None, None
                for option in cand["opportunities"]:
                    status, result = call("POST", f"/api/opportunities/{option['listing_id']}/apply",
                                          {"cover_note": "Test application from handlers_opportunities.py"}, cookie)
                    if status == 201:
                        applied_id = option["listing_id"]
                        break
                    last_error = (status, result.get("error"))
                if applied_id is None:
                    print("SKIP: no listing accepted the application. Last answer:", last_error)
                else:
                    check("apply to a listing", status, 201)
                    check("applying again is refused", call("POST", f"/api/opportunities/{applied_id}/apply", {}, cookie)[0], 409)
                    saved = db.fetch_one("SELECT status, match_score FROM applications WHERE student_id = %s AND listing_id = %s",
                                         (student["student_id"], applied_id))
                    check("application saved as 'submitted' with a score",
                          (saved["status"], saved["match_score"] is not None), ("submitted", True))
                    _, detail = call("GET", f"/api/opportunities/{applied_id}", cookie=cookie)
                    check("detail now says already applied", detail["can_apply"], False)
                    _, rec2 = call("GET", "/api/recommendations?limit=50", cookie=cookie)
                    check("recommendations no longer include it",
                          applied_id in [r["listing_id"] for r in rec2["recommendations"]], False)
                    check("apply to a missing listing", call("POST", "/api/opportunities/999999999/apply", {}, cookie)[0], 404)

        print("\nAll checks passed." if not failures else f"\nFAILED: {failures}")
    finally:
        db.close_pool()