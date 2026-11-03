"""
recommend.py - match scoring between a student and internship listings.

Score = weighted average of up to four parts (each part is 0.0 to 1.0):
    skills     S  share of the listing's REQUIRED skills that the student has
    programme  P  1.0 same programme, 0.5 same programme_group, 0.0 otherwise
    interests  I  share of the listing's tags + sector that match student interests
    location   L  1.0 same place or remote, 0.5 elsewhere but willing to relocate, 0.0 otherwise

A part with no data is LEFT OUT and the remaining weights are rescaled
(schema: "When NULL the location score is left out and the other weights are rescaled").
Result is 0 to 100, matching applications.match_score.
"""
import db

# Change these numbers here if your project documents say something different.
WEIGHTS = {"skills": 40, "programme": 25, "location": 20, "interests": 15}

# A listing can be shown to students only when all of this is true.
OPEN_LISTING_WHERE = (
    "l.status = 'open' "
    "AND l.application_deadline >= CURRENT_DATE "
    "AND l.slots_filled < l.slots "
    "AND c.verification_status = 'verified'"
)


def _norm(text):
    return (text or "").strip().lower()


# ---------------------------------------------------------------------
# Pure scoring (no database) - easy to test
# ---------------------------------------------------------------------
def score_listing(student, listing):
    """
    student: {"programme_id", "programme_group", "preferred_location", "willing_to_relocate",
              "skill_ids": set of ints, "interest_names": set of lower-case strings}
    listing: {"sector", "location", "is_remote",
              "skills": [{"id","name","required"}], "programmes": [{"id","name","group"}],
              "interests": ["tag", ...]}
    Returns {"score", "breakdown", "matched_skills", "missing_skills", "optional_skills"}.
    """
    parts = {}

    # --- Skills (only is_required = true skills count) ---
    skills = listing.get("skills") or []
    required = [s for s in skills if s.get("required")]
    matched = [s["name"] for s in required if s["id"] in student["skill_ids"]]
    missing = [s["name"] for s in required if s["id"] not in student["skill_ids"]]
    optional = [s["name"] for s in skills if not s.get("required")]
    if required:
        parts["skills"] = len(matched) / len(required)

    # --- Programme ---
    programmes = listing.get("programmes") or []
    if programmes:
        if any(p["id"] == student["programme_id"] for p in programmes):
            parts["programme"] = 1.0
        elif any(_norm(p.get("group")) == _norm(student.get("programme_group")) for p in programmes):
            parts["programme"] = 0.5
        else:
            parts["programme"] = 0.0

    # --- Interests (listing tags plus the listing sector) ---
    if student["interest_names"]:
        universe = {_norm(t) for t in (listing.get("interests") or [])}
        universe.add(_norm(listing.get("sector")))
        universe.discard("")
        if universe:
            parts["interests"] = len(universe & student["interest_names"]) / len(universe)

    # --- Location ---
    preferred = _norm(student.get("preferred_location"))
    if preferred:
        place = _norm(listing.get("location"))
        if listing.get("is_remote"):
            parts["location"] = 1.0
        elif place and (preferred in place or place in preferred):
            parts["location"] = 1.0
        elif student.get("willing_to_relocate"):
            parts["location"] = 0.5
        else:
            parts["location"] = 0.0

    # --- Combine, rescaling the weights of the parts that exist ---
    if parts:
        total_weight = sum(WEIGHTS[k] for k in parts)
        score = sum(WEIGHTS[k] * v for k, v in parts.items()) / total_weight * 100
    else:
        score = 0.0

    return {
        "score": round(score, 2),
        "breakdown": {k: round(v * 100) for k, v in parts.items()},
        "matched_skills": matched,
        "missing_skills": missing,
        "optional_skills": optional,
    }


# ---------------------------------------------------------------------
# Loading data
# ---------------------------------------------------------------------
def get_student_context(student_id):
    """Everything about a student that scoring needs, or None if the student does not exist."""
    base = db.fetch_one(
        """
        SELECT sp.student_id, sp.programme_id, sp.preferred_location,
               sp.willing_to_relocate, p.programme_group
        FROM student_profiles sp
        JOIN programmes p ON p.programme_id = sp.programme_id
        WHERE sp.student_id = %s
        """,
        (student_id,),
    )
    if base is None:
        return None
    skills = db.fetch_all(
        "SELECT s.skill_id, s.name FROM student_skills ss "
        "JOIN skills s ON s.skill_id = ss.skill_id WHERE ss.student_id = %s",
        (student_id,),
    )
    interests = db.fetch_all(
        "SELECT i.name FROM student_interests si "
        "JOIN interests i ON i.interest_id = si.interest_id WHERE si.student_id = %s",
        (student_id,),
    )
    base["skill_ids"] = {s["skill_id"] for s in skills}
    base["skill_names"] = sorted(s["name"] for s in skills)
    base["interest_names"] = {_norm(i["name"]) for i in interests}
    return base


_LISTING_SELECT = """
SELECT l.listing_id, l.title, l.description, l.sector, l.location, l.is_remote,
       l.duration_weeks, l.slots, l.slots_filled, l.application_deadline,
       l.posted_at, l.status, c.company_id, c.name AS company_name,
       EXISTS (SELECT 1 FROM applications a
               WHERE a.listing_id = l.listing_id AND a.student_id = %s) AS already_applied,
       (SELECT COALESCE(json_agg(json_build_object('id', s.skill_id, 'name', s.name,
                                                   'required', ls.is_required) ORDER BY s.name),
                        '[]'::json)
          FROM listing_skills ls JOIN skills s ON s.skill_id = ls.skill_id
         WHERE ls.listing_id = l.listing_id) AS skills,
       (SELECT COALESCE(json_agg(json_build_object('id', p.programme_id, 'name', p.name,
                                                   'group', p.programme_group) ORDER BY p.name),
                        '[]'::json)
          FROM listing_programmes lp JOIN programmes p ON p.programme_id = lp.programme_id
         WHERE lp.listing_id = l.listing_id) AS programmes,
       (SELECT COALESCE(json_agg(i.name ORDER BY i.name), '[]'::json)
          FROM listing_interests li JOIN interests i ON i.interest_id = li.interest_id
         WHERE li.listing_id = l.listing_id) AS interests
FROM listings l
JOIN companies c ON c.company_id = l.company_id
"""


def fetch_listings(student_id, where_sql, params=(), order_sql="l.application_deadline, l.listing_id", limit=None):
    """
    Run the shared listing query.
      where_sql  e.g. OPEN_LISTING_WHERE + " AND lower(l.sector) = %s"
      params     values for the %s markers in where_sql (student_id is added for you)
    Note: a literal percent sign inside where_sql must be written as %%.
    """
    sql = _LISTING_SELECT + " WHERE " + where_sql + " ORDER BY " + order_sql
    values = [student_id] + list(params)
    if limit is not None:
        sql += " LIMIT %s"
        values.append(int(limit))
    return db.fetch_all(sql, tuple(values))


def fetch_open_listings(student_id, extra_where="", params=(), order_sql="l.application_deadline, l.listing_id", limit=None):
    """Listings a student may currently apply to, optionally narrowed by extra conditions."""
    where = OPEN_LISTING_WHERE + ((" AND " + extra_where) if extra_where else "")
    return fetch_listings(student_id, where, params, order_sql, limit)


# ---------------------------------------------------------------------
# Public helpers used by the handlers
# ---------------------------------------------------------------------
def attach_score(student, listing):
    """Add match_score, match_breakdown and skill lists to a listing dict (and return it)."""
    result = score_listing(student, listing)
    listing["match_score"] = result["score"]
    listing["match_breakdown"] = result["breakdown"]
    listing["matched_skills"] = result["matched_skills"]
    listing["missing_skills"] = result["missing_skills"]
    listing["optional_skills"] = result["optional_skills"]
    return listing


def recommend_for_student(student_id, limit=20):
    """
    Open listings the student has NOT applied to yet, best match first.
    Returns [] if the student does not exist.
    """
    student = get_student_context(student_id)
    if student is None:
        return []
    listings = fetch_open_listings(student_id, extra_where="NOT EXISTS ("
                                   "SELECT 1 FROM applications a2 "
                                   "WHERE a2.listing_id = l.listing_id AND a2.student_id = %s)",
                                   params=(student_id,))
    for listing in listings:
        attach_score(student, listing)
    listings.sort(key=lambda x: (-x["match_score"], x["application_deadline"]))
    return listings[:limit]


def score_for_application(student_id, listing_id):
    """The score stored in applications.match_score when a student applies (None if not found)."""
    student = get_student_context(student_id)
    if student is None:
        return None
    rows = fetch_listings(student_id, "l.listing_id = %s", (listing_id,))
    if not rows:
        return None
    return score_listing(student, rows[0])["score"]


# ---------------------------------------------------------------------
# Self-test
#   python recommend.py              -> scoring checks (no database needed)
#   python recommend.py 3            -> also prints top matches for student_id 3
# ---------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    student = {
        "programme_id": 1, "programme_group": "computing",
        "preferred_location": "Kampala", "willing_to_relocate": False,
        "skill_ids": {1, 2}, "interest_names": {"software", "fintech"},
    }
    listing_a = {
        "sector": "Software", "location": "Kampala", "is_remote": False,
        "skills": [{"id": 1, "name": "Python", "required": True},
                   {"id": 2, "name": "SQL", "required": True},
                   {"id": 3, "name": "Docker", "required": True},
                   {"id": 4, "name": "Figma", "required": False}],
        "programmes": [{"id": 1, "name": "BSc CS", "group": "computing"}],
        "interests": ["Software"],
    }
    listing_b = {
        "sector": "Banking", "location": "Gulu", "is_remote": False, "skills": [],
        "programmes": [{"id": 9, "name": "BSc IT", "group": "computing"}], "interests": [],
    }
    listing_c = {
        "sector": "Software", "location": "Gulu", "is_remote": True, "skills": [],
        "programmes": [{"id": 5, "name": "BCom", "group": "business"}], "interests": [],
    }
    student_no_location = dict(student, preferred_location=None)

    checks = [
        ("A: strong match", score_listing(student, listing_a)["score"], 86.67),
        ("B: weak match", score_listing(student, listing_b)["score"], 20.83),
        ("C: remote, other programme", score_listing(student, listing_c)["score"], 58.33),
        ("A: no preferred location", score_listing(student_no_location, listing_a)["score"], 83.33),
    ]
    detail = score_listing(student, listing_a)
    ok = True
    for label, got, expected in checks:
        good = abs(got - expected) < 0.01
        ok = ok and good
        print(f"{'OK  ' if good else 'FAIL'} {label:<28} got {got:>6} expected {expected}")
    print("     matched:", detail["matched_skills"], "| missing:", detail["missing_skills"],
          "| optional:", detail["optional_skills"])
    print("     breakdown:", detail["breakdown"])
    print("All scoring checks passed." if ok else "SOME CHECKS FAILED - do not continue.")

    if len(sys.argv) > 1 and ok:
        try:
            sid = int(sys.argv[1])
            top = recommend_for_student(sid, limit=5)
            print(f"\nTop matches for student_id {sid}: {len(top)} found")
            for item in top:
                print(f"  {item['match_score']:>6}  {item['title']}  ({item['company_name']})")
        finally:
            db.close_pool()