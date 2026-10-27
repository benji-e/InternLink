"""Scoring one student against one opportunity (design Section 5).

All parts are computed as exact fractions so the final score never suffers
floating-point drift (Section 5.5).
"""
import math
from collections.abc import Mapping
from fractions import Fraction

from matching_engine.config import DEFAULT_CONFIG, MatchingConfig
from matching_engine.models import MatchResult, Opportunity, StudentProfile
from matching_engine.normalize import normalize, normalize_all

NEUTRAL = Fraction(1, 2)


def skills_overlap(student_skills: set[str], required_skills: set[str]) -> Fraction:
    """Section 5.2: share of the required skills the student has."""
    if not required_skills:
        return NEUTRAL
    return Fraction(len(student_skills & required_skills), len(required_skills))


FAMILY_MATCH = Fraction(3, 5)


def program_relevance(
    student_program: str, target_programs: set[str], families: dict[str, str]
) -> Fraction:
    """Section 5.3: exact 1.0, same family 0.6, open to all 0.5, else 0."""
    if student_program in target_programs:
        return Fraction(1)
    student_family = families.get(student_program)
    target_families = {families.get(p) for p in target_programs}
    if student_family is not None and student_family in target_families:
        return FAMILY_MATCH
    if not target_programs:
        return NEUTRAL
    return Fraction(0)


SECTOR_SHARE = Fraction(3, 5)
TAG_SHARE = Fraction(2, 5)


def interest_match(student_interests: set[str], sector: str, tags: set[str]) -> Fraction:
    """Section 5.4: sector hit, blended with tag coverage when the listing has tags."""
    sector_hit = Fraction(1 if sector in student_interests else 0)
    if not tags:
        return sector_hit
    tag_cover = Fraction(len(student_interests & tags), len(tags))
    return SECTOR_SHARE * sector_hit + TAG_SHARE * tag_cover


def round_half_up(value: Fraction) -> int:
    """Section 5.5: 22.5 -> 23 (Python's round() would give 22)."""
    return math.floor(value + Fraction(1, 2))


def score(
    student: StudentProfile,
    opp: Opportunity,
    cfg: MatchingConfig = DEFAULT_CONFIG,
    families: Mapping[str, str] | None = None,
) -> MatchResult:
    """Score one student against one opportunity, 0-100 (SR20).

    Pure function: no clock, database or randomness, so the same input
    always gives the same output.
    """
    skills = normalize_all(student.skills)
    required = normalize_all(opp.required_skills)
    interests = normalize_all(student.interests)

    s_skill = skills_overlap(skills, required)
    s_prog = program_relevance(student.program, set(opp.target_programs), dict(families or {}))
    s_int = interest_match(interests, normalize(opp.sector), normalize_all(opp.tags))

    total = cfg.w_skill * s_skill + cfg.w_prog * s_prog + cfg.w_int * s_int
    return MatchResult(
        score=round_half_up(100 * total),
        breakdown={
            "skills": round(float(s_skill), 3),
            "program": round(float(s_prog), 3),
            "interests": round(float(s_int), 3),
        },
        matched_skills=sorted(skills & required),
        missing_skills=sorted(required - skills),
    )
