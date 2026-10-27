"""Section 5.2: S_skill = share of the opportunity's required skills the student has."""
from fractions import Fraction

from matching_engine.scoring import skills_overlap


def test_two_of_three_required_skills_gives_two_thirds():
    assert skills_overlap({"python", "sql", "react", "git"}, {"python", "sql", "excel"}) == Fraction(2, 3)


def test_all_required_skills_gives_one():
    assert skills_overlap({"python", "sql", "excel"}, {"python", "sql"}) == 1


def test_no_matching_skills_gives_zero():
    assert skills_overlap({"photoshop"}, {"python", "sql"}) == 0


def test_no_required_skills_is_neutral_half():
    assert skills_overlap({"python"}, set()) == Fraction(1, 2)


def test_unrelated_extra_skill_does_not_lower_score():
    # The reason we don't use Jaccard similarity (Section 5.2).
    before = skills_overlap({"python", "sql"}, {"python", "sql", "excel"})
    after = skills_overlap({"python", "sql", "photoshop"}, {"python", "sql", "excel"})
    assert after == before
