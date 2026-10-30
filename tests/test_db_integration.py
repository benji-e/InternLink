"""Engine + Lubega's real schema and seed data (PR #2). Part of integration testing (5.3).

Needs a PostgreSQL 16 database with 01_schema, 02_functions_triggers,
03_views_functions and 05_seed loaded, then:
    set INTERNLINK_TEST_DSN=postgresql://postgres@localhost:5432/internlink
Skipped when INTERNLINK_TEST_DSN is not set.
"""
import os
from datetime import date

import pytest

from matching_engine.ranking import ProfileIncomplete

DSN = os.environ.get("INTERNLINK_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="INTERNLINK_TEST_DSN not set (no test database)")


@pytest.fixture
def conn():
    import psycopg

    with psycopg.connect(DSN) as connection:
        yield connection


def test_loads_seed_student_by_programme_id(conn):
    from matching_engine.db import load_inputs

    inputs = load_inputs(conn, student_id=1)
    assert inputs.student.program == "1"
    assert set(inputs.student.skills) == {"Python", "SQL", "Flask"}
    assert set(inputs.student.interests) == {"Software", "Data"}
    assert inputs.families["1"] == "computing"
    assert inputs.applied_ids == {1, 5}


def test_seed_student_1_gets_design_scores_in_order(conn):
    from matching_engine.db import recommend_for_student

    result = recommend_for_student(conn, student_id=1, today=date.today())
    assert [r.listing.opportunity_id for r in result.results] == [2, 9, 4]
    assert [r.match.score for r in result.results] == [56, 48, 21]


def test_applied_closed_and_draft_listings_never_appear(conn):
    from matching_engine.db import recommend_for_student

    result = recommend_for_student(conn, student_id=1, today=date.today(), k=50)
    shown = {r.listing.opportunity_id for r in result.results}
    assert shown.isdisjoint({1, 5, 6, 7, 8})


def test_unknown_student_gets_profile_incomplete(conn):
    from matching_engine.db import recommend_for_student

    with pytest.raises(ProfileIncomplete):
        recommend_for_student(conn, student_id=999_999, today=date.today())
