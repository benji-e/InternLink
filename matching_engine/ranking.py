"""Ranking and recommendation service (design Sections 4 and 5.7, WBS 4.6.2).

In the real app the hard filters also run inside the database query, so only
eligible listings are loaded. They are repeated here so the service is correct
on its own and can be unit-tested without a database (NFR08).
"""
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

from matching_engine.config import DEFAULT_CONFIG, MatchingConfig
from matching_engine.models import Listing, MatchResult, StudentProfile
from matching_engine.scoring import score

log = logging.getLogger(__name__)


class ProfileIncomplete(Exception):
    """Student has no program or no skills: the API returns 422 PROFILE_INCOMPLETE."""


@dataclass(frozen=True)
class Recommendation:
    listing: Listing
    match: MatchResult


@dataclass(frozen=True)
class Recommendations:
    algorithm_version: str
    results: list[Recommendation]

    @property
    def count(self) -> int:
        return len(self.results)


def is_eligible(listing: Listing, today: date, applied_ids: Iterable[int]) -> bool:
    """Section 4.1 hard filters. Yes/no only; they never change the score."""
    return (
        listing.status == "Open"
        and listing.company_verified
        and listing.deadline >= today
        and listing.slots_remaining > 0
        and listing.opportunity_id not in applied_ids
    )


def _sort_key(rec: Recommendation):
    # Score high->low, deadline soon->late, newest posting first, then id.
    return (
        -rec.match.score,
        rec.listing.deadline,
        -rec.listing.posted_at.timestamp(),
        rec.listing.opportunity_id,
    )


def recommend(
    student: StudentProfile,
    listings: Iterable[Listing],
    *,
    today: date,
    applied_ids: Iterable[int] = frozenset(),
    k: int | None = None,
    cfg: MatchingConfig = DEFAULT_CONFIG,
    families: Mapping[str, str] | None = None,
) -> Recommendations:
    """Top-K recommendations for one student, highest score first (SR03)."""
    if not student.program or not student.skills:
        raise ProfileIncomplete("Add your program and at least one skill to get recommendations")
    k = cfg.default_k if k is None else k
    if k < 1:
        raise ValueError("k must be at least 1")

    applied = set(applied_ids)
    scored = []
    for item in listings:
        if not is_eligible(item, today, applied):
            continue
        try:
            match = score(student, item.opportunity, cfg, families)
        except Exception:
            # Section 9: one corrupt listing must not fail the whole list.
            log.warning("Skipped listing %s: could not score it", item.opportunity_id, exc_info=True)
            continue
        if match.score >= cfg.min_score:
            scored.append(Recommendation(item, match))

    scored.sort(key=_sort_key)
    return Recommendations(cfg.algorithm_version, scored[: min(k, cfg.max_k)])
