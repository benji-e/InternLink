"""
handlers_applications.py - track applications, view status, withdraw, dashboard summary.

Routes (all need a logged-in student):
    GET  /api/applications
    GET  /api/applications/<id>
    POST /api/applications/<id>/withdraw
    GET  /api/dashboard
"""
from psycopg2 import errors as pg_errors

import auth_utils
import db
import recommend
from handlers_profile import load_profile
from router import HttpError, route

STATUSES = ("submitted", "under_review", "shortlisted", "accepted", "rejected", "withdrawn")
PENDING_STATUSES = ("submitted", "under_review", "shortlisted")      # can still be withdrawn
PER_PAGE_DEFAULT = 10
PER_PAGE_MAX = 50

STATUS_INFO = {
    "submitted": ("Submitted", "Your application has been sent and is waiting for the company to review it."),
    "under_review": ("Under review", "The company is reviewing your application."),
    "shortlisted": ("Shortlisted", "Good news: you are on the company's shortlist. They may contact you."),
    "accepted": ("Accepted", "Congratulations! The company accepted you. Your university will now confirm the placement."),
    "rejected": ("Not selected", "The company did not select you for this opportunity. Keep applying."),
    "withdrawn": ("Withdrawn", "You withdrew this application."),
}
PLACEMENT_LABELS = {
    "pending": "Awaiting university approval",
    "confirmed": "Placement confirmed",
    "rejected": "Placement not approved",
    "completed": "Placement completed",
}


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _query_int(req, name, low, high):
    raw = (req.query.get(name) or "").strip()
    if not raw:
        return None
    if not (raw.isascii() and raw.isdigit()) or not low <= int(raw) <= high:
        raise HttpError(400, f"'{name}' must be a number from {low} to {high}.")
    return int(raw)


def _shape(row, detail=False):
    label, description = STATUS_INFO.get(row["status"], (row["status"], ""))
    item = {
        "application_id": row["application_id"],
        "status": row["status"],
        "status_label": label,
        "status_description": description,
        "can_withdraw": row["status"] in PENDING_STATUSES,
        "match_score": row["match_score"],
        "submitted_at": row["submitted_at"],
        "status_changed_at": row["status_changed_at"],
        "listing": {
            "listing_id": row["listing_id"],
            "title": row["title"],
            "company_name": row["company_name"],
            "sector": row["sector"],
            "location": row["location"],
            "is_remote": row["is_remote"],
            "duration_weeks": row["duration_weeks"],
            "application_deadline": row["application_deadline"],
        },
        "placement": None,
    }
    if row.get("placement_status"):
        item["placement"] = {
            "status": row["placement_status"],
            "label": PLACEMENT_LABELS.get(row["placement_status"], row["placement_status"]),
            "start_date": row["start_date"],
            "end_date": row["end_date"],
        }
        if detail and row["placement_status"] == "rejected":
            item["placement"]["rejection_reason"] = row.get("placement_rejection_reason")
    return item


_APPLICATION_SELECT = """
SELECT a.application_id, a.status, a.match_score, a.cover_note, a.submitted_at, a.status_changed_at,
       l.listing_id, l.title, l.sector, l.location, l.is_remote, l.duration_weeks,
       l.application_deadline, c.name AS company_name,
       pl.placement_id, pl.status AS placement_status, pl.start_date, pl.end_date,
       pl.rejection_reason AS placement_rejection_reason
FROM applications a
JOIN listings l  ON l.listing_id = a.listing_id
JOIN companies c ON c.company_id = l.company_id
LEFT JOIN placements pl ON pl.application_id = a.application_id
"""


def _status_counts(student_id):
    rows = db.fetch_all(
        "SELECT status, count(*) AS n FROM applications WHERE student_id = %s GROUP BY status",
        (student_id,),
    )
    counts = {status: 0 for status in STATUSES}
    for row in rows:
        counts[row["status"]] = row["n"]
    return counts


# ---------------------------------------------------------------------
# List my applications
# ---------------------------------------------------------------------
@route("GET", "/api/applications")
@auth_utils.student_required
def list_applications(req):
    student_id = req.user["student_id"]

    status = (req.query.get("status") or "").strip().lower()
    if status and status not in STATUSES:
        raise HttpError(400, "Status must be one of: " + ", ".join(STATUSES) + ".")
    page = _query_int(req, "page", 1, 10000) or 1
    per_page = _query_int(req, "per_page", 1, PER_PAGE_MAX) or PER_PAGE_DEFAULT

    counts = _status_counts(student_id)
    total = counts[status] if status else sum(counts.values())

    where, params = "a.student_id = %s", [student_id]
    if status:
        where += " AND a.status = %s"
        params.append(status)
    rows = db.fetch_all(
        _APPLICATION_SELECT + " WHERE " + where
        + " ORDER BY a.status_changed_at DESC, a.application_id DESC LIMIT %s OFFSET %s",
        tuple(params + [per_page, (page - 1) * per_page]),
    )
    return {
        "applications": [_shape(row) for row in rows],
        "counts": counts,
        "total": total,
        "page": page,
        "pages": max(1, -(-total // per_page)),
        "per_page": per_page,
    }


# ---------------------------------------------------------------------
# One application
# ---------------------------------------------------------------------
@route("GET", "/api/applications/<int:application_id>")
@auth_utils.student_required
def get_application(req):
    application_id = req.params["application_id"]
    user_id = req.user["user_id"]
    student_id = req.user["student_id"]

    row = db.fetch_one(
        _APPLICATION_SELECT + " WHERE a.application_id = %s AND a.student_id = %s",
        (application_id, student_id),
    )
    if row is None:
        raise HttpError(404, "Application not found.")        # same answer for "not yours" and "does not exist"

    item = _shape(row, detail=True)
    item["cover_note"] = row["cover_note"]

    # Full listing details (description and skills) for the detail page.
    listing_rows = recommend.fetch_listings(student_id, "l.listing_id = %s", (row["listing_id"],))
    if listing_rows:
        listing = listing_rows[0]
        item["listing"]["description"] = listing["description"]
        item["listing"]["skills"] = [{"name": s["name"], "required": s["required"]} for s in listing["skills"]]

    # Timeline: the schema keeps no status history table, so we show what we know for sure.
    timeline = [{"label": "Application submitted", "at": row["submitted_at"]}]
    if row["status"] != "submitted":
        timeline.append({"label": f"Status: {item['status_label']}", "at": row["status_changed_at"]})
    item["timeline"] = timeline

    # Updates sent to this student about the application or its placement (from notifications).
    updates = db.fetch_all(
        """
        SELECT type, title, message, created_at
        FROM notifications
        WHERE user_id = %s AND channel = 'in_app'
          AND ((related_type = 'applications' AND related_id = %s)
               OR (related_type = 'placements' AND related_id = %s))
        ORDER BY created_at DESC
        LIMIT 20
        """,
        (user_id, application_id, row["placement_id"] if row["placement_id"] else -1),
    )
    item["updates"] = updates
    return {"application": item}


# ---------------------------------------------------------------------
# Withdraw
# ---------------------------------------------------------------------
_WITHDRAW_REFUSALS = {
    "withdrawn": "You have already withdrawn this application.",
    "accepted": "An accepted application cannot be withdrawn here. Please contact the company or your university coordinator.",
    "rejected": "This application was already declined, so it cannot be withdrawn.",
}


@route("POST", "/api/applications/<int:application_id>/withdraw")
@auth_utils.student_required
def withdraw_application(req):
    application_id = req.params["application_id"]
    user_id = req.user["user_id"]
    student_id = req.user["student_id"]

    try:
        with db.transaction(user_id=user_id) as cur:
            # One atomic statement: it only succeeds if the application is yours AND still pending.
            cur.execute(
                """
                UPDATE applications
                SET status = 'withdrawn', status_changed_at = now(), updated_at = now()
                WHERE application_id = %s AND student_id = %s
                  AND status IN ('submitted', 'under_review', 'shortlisted')
                RETURNING application_id, status, status_changed_at
                """,
                (application_id, student_id),
            )
            updated = cur.fetchone()
            if updated is None:
                cur.execute("SELECT status FROM applications WHERE application_id = %s AND student_id = %s",
                            (application_id, student_id))
                existing = cur.fetchone()
                if existing is None:
                    raise HttpError(404, "Application not found.")
                raise HttpError(409, _WITHDRAW_REFUSALS.get(existing["status"], "This application cannot be withdrawn."))
            result = dict(updated)
    except pg_errors.RaiseException as exc:                 # a rule raised on purpose by a database trigger
        raise HttpError(400, (exc.diag.message_primary or "The application could not be withdrawn.")[:200])
    except (pg_errors.CheckViolation, pg_errors.ForeignKeyViolation):
        raise HttpError(400, "The application could not be withdrawn.")

    auth_utils.audit("application_withdrawn", user_id, "student", req.client_ip, "applications", application_id)
    return {"message": "Application withdrawn.", "application": result}


# ---------------------------------------------------------------------
# Dashboard summary
# ---------------------------------------------------------------------
@route("GET", "/api/dashboard")
@auth_utils.student_required
def dashboard(req):
    student_id = req.user["student_id"]
    user_id = req.user["user_id"]

    profile_data = load_profile(user_id)
    profile = profile_data["profile"]
    counts = _status_counts(student_id)

    recent = db.fetch_all(
        _APPLICATION_SELECT + " WHERE a.student_id = %s "
        "ORDER BY a.status_changed_at DESC, a.application_id DESC LIMIT 5",
        (student_id,),
    )
    placements = db.fetch_all(
        """
        SELECT pl.status, pl.start_date, pl.end_date, l.title, c.name AS company_name
        FROM placements pl
        JOIN applications a ON a.application_id = pl.application_id
        JOIN listings l     ON l.listing_id = a.listing_id
        JOIN companies c    ON c.company_id = l.company_id
        WHERE a.student_id = %s AND pl.status IN ('pending', 'confirmed')
        ORDER BY pl.created_at DESC
        """,
        (student_id,),
    )
    for placement in placements:
        placement["label"] = PLACEMENT_LABELS.get(placement["status"], placement["status"])

    return {
        "student": {
            "full_name": profile["full_name"],
            "university": profile["university"]["name"],
            "programme": profile["programme"]["name"],
            "verified": profile["verified"],
        },
        "completeness": profile_data["completeness"],
        "applications": {
            "total": sum(counts.values()),
            "active": sum(counts[s] for s in PENDING_STATUSES),
            "by_status": counts,
            "recent": [_shape(row) for row in recent],
        },
        "placements": placements,
    }


# ---------------------------------------------------------------------
# Self-test
#   python handlers_applications.py              read-only checks
#   python handlers_applications.py --withdraw   ALSO withdraws one pending application of the
#                                                test account (this stays in the database)
# ---------------------------------------------------------------------
if __name__ == "__main__":
    import json
    import sys

    import config
    from router import Request, router

    def call(method, path, cookie=None):
        headers = {"X-Requested-With": "InternLink"}
        if cookie:
            headers["Cookie"] = f"{config.SESSION_COOKIE}={cookie}"
        resp = router.dispatch(Request(method, path, headers, b"", "127.0.0.1"))
        return resp.status, (json.loads(resp.body) if resp.body else {})

    failures = []

    def check(label, got, expected):
        good = got == expected
        if not good:
            failures.append(label)
        print(f"{'OK  ' if good else 'FAIL'} {label:<48} {got}" + ("" if good else f"  (expected {expected})"))

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

        check("list without logging in", call("GET", "/api/applications")[0], 401)
        check("bad status filter", call("GET", "/api/applications?status=banana", cookie)[0], 400)
        check("bad page value", call("GET", "/api/applications?page=0", cookie)[0], 400)

        status, data = call("GET", "/api/applications", cookie)
        check("list my applications", status, 200)
        check("status counts add up to the total", sum(data["counts"].values()), data["total"])
        print(f"     {data['total']} applications: { {k: v for k, v in data['counts'].items() if v} }")

        status, dash = call("GET", "/api/dashboard", cookie)
        check("dashboard summary", status, 200)
        check("dashboard total matches the list", dash["applications"]["total"], data["total"])
        print(f"     profile completeness: {dash['completeness']['percent']}%, verified: {dash['student']['verified']}")

        check("unknown application gives 404", call("GET", "/api/applications/999999999", cookie)[0], 404)
        check("withdrawing an unknown application", call("POST", "/api/applications/999999999/withdraw", cookie)[0], 404)

        other = db.fetch_one("SELECT application_id FROM applications WHERE student_id <> %s LIMIT 1",
                             (student["student_id"],))
        if other:
            check("another student's application gives 404",
                  call("GET", f"/api/applications/{other['application_id']}", cookie)[0], 404)
            check("cannot withdraw another student's application",
                  call("POST", f"/api/applications/{other['application_id']}/withdraw", cookie)[0], 404)
        else:
            print("SKIP  cross-student checks (no applications from other students exist)")

        if data["total"] == 0:
            print("\nThis test account has no applications yet, so the detail/withdraw checks are skipped.")
            print("Run  python handlers_opportunities.py --apply  to create one, then run this again.")
        else:
            first = data["applications"][0]
            aid = first["application_id"]
            status, one = call("GET", f"/api/applications/{aid}", cookie)
            check("view one application", status, 200)
            app = one["application"]
            check("detail has timeline and listing text", ("timeline" in app, "description" in app["listing"]), (True, True))
            print(f"     status: {app['status']} - {app['status_label']}; updates: {len(app['updates'])}")

            some = next((s for s in STATUSES if data["counts"][s] > 0), None)
            _, filtered = call("GET", f"/api/applications?status={some}", cookie)
            check(f"filter by '{some}' only returns that status",
                  all(a["status"] == some for a in filtered["applications"]), True)

            if "--withdraw" in sys.argv:
                pending = db.fetch_one(
                    "SELECT application_id FROM applications WHERE student_id = %s "
                    "AND status IN ('submitted','under_review','shortlisted') ORDER BY application_id LIMIT 1",
                    (student["student_id"],),
                )
                if pending is None:
                    print("SKIP  withdraw checks (this account has no pending application)")
                else:
                    pid = pending["application_id"]
                    status, _ = call("POST", f"/api/applications/{pid}/withdraw", cookie)
                    check("withdraw a pending application", status, 200)
                    saved = db.fetch_one("SELECT status FROM applications WHERE application_id = %s", (pid,))
                    check("database now says 'withdrawn'", saved["status"], "withdrawn")

        print("\nAll checks passed." if not failures else f"\nFAILED: {failures}")
    finally:
        db.close_pool()