"""Section 4 + 5.7 recommend(): hard filters, MIN_SCORE, sorting, top-K (SR03)."""
import logging
from dataclasses import replace
from datetime import date, datetime

import pytest

from matching_engine.models import Listing, Opportunity, StudentProfile
from matching_engine.ranking import ProfileIncomplete, recommend

TODAY = date(2026, 10, 26)
FAMILIES = {"BSc SE": "computing", "BSc CS": "computing", "BSc IT": "computing"}

STUDENT = StudentProfile(
    program="BSc SE",
    skills=["python", "sql", "react", "git"],
    interests=["fintech", "data science"],
)


def listing(opportunity_id, opp, **overrides):
    """An open, verified, in-date listing with free slots, unless overridden."""
    base = Listing(
        opportunity_id=opportunity_id,
        title=f"Listing {opportunity_id}",
        company="Example Ltd",
        opportunity=opp,
        status="Open",
        company_verified=True,
        deadline=date(2026, 11, 30),
        slots_remaining=2,
        posted_at=datetime(2026, 10, 1, 9, 0),
    )
    return replace(base, **overrides)


# Section 6 worked example
DATA_ANALYST = Opportunity("fintech", ["BSc CS", "BSc SE"], ["python", "sql", "excel"], ["data science", "banking"])
NETWORK_SUPPORT = Opportunity("telecom", ["BSc IT"], ["networking", "linux", "git"], ["infrastructure"])
FRONTEND_DEV = Opportunity("software", ["BSc SE", "BSc CS"], ["react", "javascript", "css"], ["web development"])
# Scores 81 for STUDENT: a strong match used to probe the filters
GOOD = DATA_ANALYST
# Scores 0 for STUDENT
NO_MATCH = Opportunity("health", ["BSc Nursing"], ["nursing"], ["clinical"])


def ids(result):
    return [r.listing.opportunity_id for r in result.results]


def run(listings, **kwargs):
    return recommend(STUDENT, listings, today=TODAY, families=FAMILIES, **kwargs)


# ---- Ranking -----------------------------------------------------------------

def test_worked_example_is_ranked_highest_score_first():
    result = run([listing(1, NETWORK_SUPPORT), listing(2, DATA_ANALYST), listing(3, FRONTEND_DEV)])
    assert ids(result) == [2, 3, 1]
    assert [r.match.score for r in result.results] == [81, 50, 36]


def test_result_reports_algorithm_version_and_count():
    result = run([listing(1, GOOD), listing(2, FRONTEND_DEV)])
    assert result.algorithm_version == "v1"
    assert result.count == 2


# ---- Hard filters (Section 4.1) ----------------------------------------------

def test_closed_listing_is_left_out():
    assert ids(run([listing(1, GOOD, status="Closed"), listing(2, GOOD)])) == [2]


def test_database_lower_case_status_counts_as_open():
    # Lubega's schema stores 'open' / 'closed' in lower case.
    assert ids(run([listing(1, GOOD, status="open"), listing(2, GOOD, status="closed")])) == [1]


def test_unverified_company_is_left_out():
    assert ids(run([listing(1, GOOD, company_verified=False), listing(2, GOOD)])) == [2]


def test_listing_past_its_deadline_is_left_out():
    assert ids(run([listing(1, GOOD, deadline=date(2026, 10, 25)), listing(2, GOOD)])) == [2]


def test_listing_closing_today_is_still_shown():
    assert ids(run([listing(1, GOOD, deadline=TODAY)])) == [1]


def test_full_listing_is_left_out():
    assert ids(run([listing(1, GOOD, slots_remaining=0), listing(2, GOOD)])) == [2]


def test_listing_already_applied_to_is_left_out():
    assert ids(run([listing(1, GOOD), listing(2, GOOD)], applied_ids={1})) == [2]


# ---- MIN_SCORE ---------------------------------------------------------------

def test_scores_below_min_score_are_dropped():
    assert ids(run([listing(1, NO_MATCH), listing(2, GOOD)])) == [2]


# ---- Tie-breaking (Section 5.7) ----------------------------------------------

def test_equal_scores_closing_sooner_come_first():
    later = listing(1, GOOD, deadline=date(2026, 12, 1))
    sooner = listing(2, GOOD, deadline=date(2026, 11, 1))
    assert ids(run([later, sooner])) == [2, 1]


def test_equal_scores_and_deadline_newer_posting_comes_first():
    older = listing(1, GOOD, posted_at=datetime(2026, 9, 1))
    newer = listing(2, GOOD, posted_at=datetime(2026, 10, 1))
    assert ids(run([older, newer])) == [2, 1]


def test_everything_equal_lower_id_comes_first():
    assert ids(run([listing(9, GOOD), listing(4, GOOD), listing(7, GOOD)])) == [4, 7, 9]


# ---- Top-K -------------------------------------------------------------------

def test_returns_ten_by_default():
    assert run([listing(i, GOOD) for i in range(1, 16)]).count == 10


def test_k_is_capped_at_max_k():
    assert run([listing(i, GOOD) for i in range(1, 61)], k=500).count == 50


def test_k_below_one_is_rejected():
    with pytest.raises(ValueError):
        run([listing(1, GOOD)], k=0)


def test_fewer_than_k_good_matches_returns_a_shorter_list():
    assert run([listing(1, GOOD), listing(2, NO_MATCH)]).count == 1


# ---- Errors (Sections 4 and 9) -----------------------------------------------

def test_student_without_program_gets_profile_incomplete():
    with pytest.raises(ProfileIncomplete):
        recommend(StudentProfile(program="", skills=["python"]), [], today=TODAY)


def test_student_without_skills_gets_profile_incomplete():
    with pytest.raises(ProfileIncomplete):
        recommend(StudentProfile(program="BSc SE", skills=[]), [], today=TODAY)


def test_one_bad_listing_is_skipped_and_logged(caplog):
    corrupt = Opportunity("fintech", ["BSc SE"], None, [])  # required_skills missing
    with caplog.at_level(logging.WARNING):
        result = run([listing(1, corrupt), listing(2, GOOD)])
    assert ids(result) == [2]
    assert "1" in caplog.text
