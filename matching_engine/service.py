"""Recommendation service (WBS 4.6.2).

Scoring and ranking are done by the database function fn_recommendations
(Lubega's design, PR #2). This service adds what the API needs on top:
listing details, matched/missing skills for "why recommended", the
"complete your profile" check, and a time limit (NFR07).
"""
import logging
from dataclasses import dataclass, field
from datetime import date

from matching_engine.config import DEFAULT_CONFIG, ServiceConfig

log = logging.getLogger(__name__)


class ProfileIncomplete(Exception):
    """No student profile, or no skills: the API returns 422 PROFILE_INCOMPLETE."""


class MatchingUnavailable(Exception):
    """Database error or timeout: the API returns 503 and the UI shows Retry (NFR07)."""


@dataclass(frozen=True)
class Recommendation:
    rank: int
    listing_id: int
    title: str
    company: str
    deadline: date
    score: int
    breakdown: dict[str, float | None]
    applied: bool
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Recommendations:
    algorithm: str
    results: list[Recommendation]

    @property
    def count(self) -> int:
        return len(self.results)


PROFILE_SQL = """
    SELECT (SELECT count(*) FROM student_skills ss WHERE ss.student_id = sp.student_id) AS skills
    FROM student_profiles sp WHERE sp.student_id = %(sid)s"""

RECOMMEND_SQL = """
    SELECT r.rank, r.listing_id, r.score, r.p, r.s, r.i, r.l, r.applied,
           l.title, c.name AS company, l.application_deadline AS deadline,
           COALESCE(array_agg(sk.name ORDER BY sk.name) FILTER (WHERE ss.skill_id IS NOT NULL), '{}') AS matched,
           COALESCE(array_agg(sk.name ORDER BY sk.name)
                    FILTER (WHERE sk.skill_id IS NOT NULL AND ss.skill_id IS NULL), '{}') AS missing
    FROM fn_recommendations(%(sid)s, %(limit)s) r
    JOIN listings l ON l.listing_id = r.listing_id
    JOIN companies c ON c.company_id = l.company_id
    LEFT JOIN listing_skills ls ON ls.listing_id = r.listing_id AND ls.is_required
    LEFT JOIN skills sk ON sk.skill_id = ls.skill_id
    LEFT JOIN student_skills ss ON ss.skill_id = ls.skill_id AND ss.student_id = %(sid)s
    GROUP BY r.rank, r.listing_id, r.score, r.p, r.s, r.i, r.l, r.applied, l.title, c.name, l.application_deadline
    ORDER BY r.rank"""


def _part(value) -> float | None:
    return None if value is None else round(float(value), 3)


def _to_recommendation(row) -> Recommendation:
    return Recommendation(
        rank=row["rank"],
        listing_id=row["listing_id"],
        title=row["title"],
        company=row["company"],
        deadline=row["deadline"],
        score=row["score"],
        # location is None when the student has no preferred location (weights rescaled)
        breakdown={"programme": _part(row["p"]), "skills": _part(row["s"]),
                   "interests": _part(row["i"]), "location": _part(row["l"])},
        applied=row["applied"],
        matched_skills=list(row["matched"]),
        missing_skills=list(row["missing"]),
    )


def recommend_for_student(
    conn, student_id: int, *, k: int | None = None, cfg: ServiceConfig = DEFAULT_CONFIG
) -> Recommendations:
    """Top-K recommendations for one student (SR03). `conn` is a psycopg connection."""
    import psycopg
    from psycopg.rows import dict_row

    k = cfg.default_k if k is None else k
    if k < 1:
        raise ValueError("k must be at least 1")
    params = {"sid": student_id, "limit": min(k, cfg.max_k)}

    try:
        with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            timeout_ms = f"{int(cfg.timeout_seconds * 1000)}ms"
            cur.execute("SELECT set_config('statement_timeout', %s, true)", (timeout_ms,))
            profile = cur.execute(PROFILE_SQL, params).fetchone()
            if profile is None or profile["skills"] == 0:
                raise ProfileIncomplete("Add your programme and at least one skill to get recommendations")
            rows = cur.execute(RECOMMEND_SQL, params).fetchall()
    except psycopg.Error as exc:
        log.warning("Recommendations failed for student %s", student_id, exc_info=True)
        raise MatchingUnavailable("Couldn't load recommendations") from exc

    return Recommendations(cfg.algorithm, [_to_recommendation(r) for r in rows])
