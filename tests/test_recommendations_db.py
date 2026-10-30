"""Recommendation service on top of Lubega's fn_recommendations (PR #2).

Integration tests (WBS 4.6.2, 5.3). They need PostgreSQL 16 with 01_schema,
02_functions_triggers, 03_views_functions and 05_seed loaded, and:
    set INTERNLINK_TEST_DSN=postgresql://postgres@localhost:54329/internlink
Skipped when INTERNLINK_TEST_DSN is not set. Every test runs in a transaction
that is rolled back, so the database is left unchanged.
"""
import os
from dataclasses import replace

import pytest

from matching_engine.config import DEFAULT_CONFIG
from matching_engine.service import (
    MatchingUnavailable,
    ProfileIncomplete,
    recommend_for_student,
    student_id_for_user,
)

DSN = os.environ.get("INTERNLINK_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="INTERNLINK_TEST_DSN not set (no test database)")


@pytest.fixture
def conn():
    import psycopg

    connection = psycopg.connect(DSN)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def by_id(result):
    return {r.listing_id: r for r in result.results}


# ---- Uses fn_recommendations' scores and order --------------------------------

def test_seed_student_1_gets_fn_recommendations_scores_in_rank_order(conn):
    result = recommend_for_student(conn, 1)
    assert [r.listing_id for r in result.results] == [1, 5, 9, 2, 4]
    assert [r.score for r in result.results] == [79, 53, 48, 38, 28]
    assert [r.rank for r in result.results] == [1, 2, 3, 4, 5]


def test_breakdown_has_the_four_parts(conn):
    top = recommend_for_student(conn, 1).results[0]
    assert top.breakdown == {"programme": 1.0, "skills": 0.667, "interests": 0.5, "location": 1.0}


def test_listings_already_applied_to_are_flagged_not_hidden(conn):
    rows = by_id(recommend_for_student(conn, 1))
    assert rows[1].applied is True
    assert rows[9].applied is False


# ---- Extra detail the API and Recommendations UI need ------------------------

def test_matched_and_missing_skills_use_required_skills_only(conn):
    developer = by_id(recommend_for_student(conn, 1))[1]
    assert developer.matched_skills == ["Python", "SQL"]
    assert developer.missing_skills == ["React"]  # Git is optional, so not listed


def test_result_has_title_company_and_deadline(conn):
    developer = by_id(recommend_for_student(conn, 1))[1]
    assert developer.title == "Software Developer Intern"
    assert developer.company == "TechCo Ltd"
    assert developer.deadline is not None


def test_k_limits_the_list(conn):
    assert recommend_for_student(conn, 1, k=2).count == 2


def test_k_below_one_is_rejected(conn):
    with pytest.raises(ValueError):
        recommend_for_student(conn, 1, k=0)


# ---- SR20: more overlap never lowers the score -------------------------------

def test_adding_a_matching_skill_never_lowers_a_score(conn):
    before = {r.listing_id: r.score for r in recommend_for_student(conn, 1, k=50).results}
    conn.execute("INSERT INTO student_skills VALUES (1, 4)")  # React
    after = {r.listing_id: r.score for r in recommend_for_student(conn, 1, k=50).results}
    assert all(after[i] >= before[i] for i in before)


@pytest.mark.xfail(strict=True, reason="Known SR20 defect in fn_recommendations: interest score divides "
                   "by the student's interest count. Fix proposed to Lubega; remove this mark once merged.")
def test_adding_an_interest_never_lowers_a_score(conn):
    before = {r.listing_id: r.score for r in recommend_for_student(conn, 1, k=50).results}
    conn.execute("INSERT INTO student_interests VALUES (1, 6)")  # Agriculture
    after = {r.listing_id: r.score for r in recommend_for_student(conn, 1, k=50).results}
    assert all(after[i] >= before[i] for i in before if i in after)


# ---- Logged-in user -> student profile ---------------------------------------

def test_student_user_maps_to_their_profile(conn):
    assert student_id_for_user(conn, 10) == 1


def test_user_without_student_profile_maps_to_none(conn):
    assert student_id_for_user(conn, 5) is None  # an employer
    assert student_id_for_user(conn, 999_999) is None


# ---- Errors ------------------------------------------------------------------

def test_unknown_student_gets_profile_incomplete(conn):
    with pytest.raises(ProfileIncomplete):
        recommend_for_student(conn, 999_999)


def test_student_without_skills_gets_profile_incomplete(conn):
    conn.execute("DELETE FROM student_skills WHERE student_id = 7")
    with pytest.raises(ProfileIncomplete):
        recommend_for_student(conn, 7)


def test_slow_query_is_stopped_and_reported_as_unavailable(conn):
    import psycopg

    # Another session locks listings, so the recommendation query has to wait.
    with psycopg.connect(DSN) as locker:
        locker.execute("LOCK TABLE listings IN ACCESS EXCLUSIVE MODE")
        fast_timeout = replace(DEFAULT_CONFIG, timeout_seconds=0.5)
        with pytest.raises(MatchingUnavailable):
            recommend_for_student(conn, 1, cfg=fast_timeout)
        locker.rollback()
