"""Turning rows from Lubega's schema (PR #2) into engine inputs. No database needed."""
from datetime import date, datetime, timezone

from matching_engine.db import families_from_rows, listing_from_row, student_from_rows
from matching_engine.models import Listing, Opportunity, StudentProfile


def test_student_program_is_its_programme_id_as_text():
    # Two programmes are both called "BSc Computer Science" (ids 2 and 5), so match by id.
    student = student_from_rows({"programme_id": 2, "year_of_study": 3}, ["Python", "SQL"], ["Data"])
    assert student == StudentProfile(program="2", skills=["Python", "SQL"], interests=["Data"], year_of_study=3)


def test_families_map_programme_id_to_programme_group():
    rows = [{"programme_id": 1, "programme_group": "computing"}, {"programme_id": 4, "programme_group": "business"}]
    assert families_from_rows(rows) == {"1": "computing", "4": "business"}


def test_open_listing_row_becomes_a_listing():
    posted = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    row = {
        "listing_id": 9,
        "title": "Remote Research Assistant",
        "company_name": "NGO Data Hub",
        "sector": "Data",
        "application_deadline": date(2026, 11, 29),
        "posted_at": posted,
        "slots_remaining": 2,
        "required_skills": ["Data Analysis", "Python", "Statistics"],
        "programme_ids": [2, 5],
        "tags": ["Research"],
    }
    assert listing_from_row(row) == Listing(
        opportunity_id=9,
        title="Remote Research Assistant",
        company="NGO Data Hub",
        opportunity=Opportunity(
            sector="Data",
            target_programs=["2", "5"],
            required_skills=["Data Analysis", "Python", "Statistics"],
            tags=["Research"],
        ),
        status="open",
        company_verified=True,  # v_open_listings only returns verified companies
        deadline=date(2026, 11, 29),
        slots_remaining=2,
        posted_at=posted,
    )
