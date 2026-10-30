"""Load engine inputs from the InternLink PostgreSQL schema (PR #2, WBS 3.2 / 4.2.2).

The database only supplies data and the hard filters (via v_open_listings).
All scoring and ranking stays in the Python engine, as agreed in design 3.4.
"""
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from matching_engine.config import DEFAULT_CONFIG, MatchingConfig
from matching_engine.models import Listing, Opportunity, StudentProfile
from matching_engine.ranking import ProfileIncomplete, Recommendations, recommend

STUDENT_SQL = "SELECT programme_id, year_of_study FROM student_profiles WHERE student_id = %(sid)s"
STUDENT_SKILLS_SQL = """
    SELECT s.name FROM student_skills ss JOIN skills s USING (skill_id)
    WHERE ss.student_id = %(sid)s ORDER BY s.name"""
STUDENT_INTERESTS_SQL = """
    SELECT i.name FROM student_interests si JOIN interests i USING (interest_id)
    WHERE si.student_id = %(sid)s ORDER BY i.name"""
# Every status counts: (student_id, listing_id) is unique, so they can't apply twice.
APPLIED_SQL = "SELECT listing_id FROM applications WHERE student_id = %(sid)s"
FAMILIES_SQL = "SELECT programme_id, programme_group FROM programmes"
# v_open_listings already applies the hard filters (open, verified, in date, slots left);
# applied listings are dropped here too so they are never loaded (design 4.1, 8.1).
CANDIDATES_SQL = """
    SELECT v.listing_id, v.title, v.company_name, v.sector, v.application_deadline,
           v.posted_at, v.slots_remaining, v.required_skills,
           COALESCE((SELECT array_agg(lp.programme_id ORDER BY lp.programme_id)
                     FROM listing_programmes lp WHERE lp.listing_id = v.listing_id), '{}') AS programme_ids,
           COALESCE((SELECT array_agg(i.name ORDER BY i.name)
                     FROM listing_interests li JOIN interests i USING (interest_id)
                     WHERE li.listing_id = v.listing_id), '{}') AS tags
    FROM v_open_listings v
    WHERE NOT EXISTS (SELECT 1 FROM applications a
                      WHERE a.student_id = %(sid)s AND a.listing_id = v.listing_id)"""


@dataclass(frozen=True)
class RecommendationInputs:
    student: StudentProfile
    listings: list[Listing]
    applied_ids: set[int]
    families: dict[str, str]


def student_from_rows(
    profile: Mapping, skill_names: Sequence[str], interest_names: Sequence[str]
) -> StudentProfile:
    # Match programmes by id: names are not unique across universities.
    return StudentProfile(
        program=str(profile["programme_id"]),
        skills=list(skill_names),
        interests=list(interest_names),
        year_of_study=profile["year_of_study"],
    )


def families_from_rows(rows: Iterable[Mapping]) -> dict[str, str]:
    return {str(r["programme_id"]): r["programme_group"] for r in rows}


def listing_from_row(row: Mapping) -> Listing:
    return Listing(
        opportunity_id=row["listing_id"],
        title=row["title"],
        company=row["company_name"],
        opportunity=Opportunity(
            sector=row["sector"],
            target_programs=[str(p) for p in row["programme_ids"]],
            required_skills=list(row["required_skills"]),
            tags=list(row["tags"]),
        ),
        status="open",
        company_verified=True,  # v_open_listings only returns verified companies
        deadline=row["application_deadline"],
        slots_remaining=row["slots_remaining"],
        posted_at=row["posted_at"],
    )


def load_inputs(conn, student_id: int) -> RecommendationInputs:
    """Read everything the engine needs for one student. `conn` is a psycopg connection."""
    from psycopg.rows import dict_row

    params = {"sid": student_id}
    with conn.cursor(row_factory=dict_row) as cur:
        profile = cur.execute(STUDENT_SQL, params).fetchone()
        if profile is None:
            raise ProfileIncomplete("No student profile found")
        skills = [r["name"] for r in cur.execute(STUDENT_SKILLS_SQL, params)]
        interests = [r["name"] for r in cur.execute(STUDENT_INTERESTS_SQL, params)]
        applied = {r["listing_id"] for r in cur.execute(APPLIED_SQL, params)}
        families = families_from_rows(cur.execute(FAMILIES_SQL))
        listings = [listing_from_row(r) for r in cur.execute(CANDIDATES_SQL, params)]
    return RecommendationInputs(student_from_rows(profile, skills, interests), listings, applied, families)


def recommend_for_student(
    conn,
    student_id: int,
    *,
    today: date,
    k: int | None = None,
    cfg: MatchingConfig = DEFAULT_CONFIG,
) -> Recommendations:
    """Load from the database, then score and rank in Python (SR03)."""
    inputs = load_inputs(conn, student_id)
    return recommend(
        inputs.student,
        inputs.listings,
        today=today,
        applied_ids=inputs.applied_ids,
        k=k,
        cfg=cfg,
        families=inputs.families,
    )
