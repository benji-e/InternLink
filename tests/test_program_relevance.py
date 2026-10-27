"""Section 5.3: S_prog."""
from fractions import Fraction

from matching_engine.scoring import program_relevance

# Program -> family lookup (real table comes from seed data, WBS 4.2.2).
FAMILIES = {
    "bsc se": "computing",
    "bsc cs": "computing",
    "bsc it": "computing",
    "bsc is": "computing",
    "bsc statistics": "statistics",
    "bsc nursing": "health",
}


def test_exact_program_match_gives_one():
    assert program_relevance("bsc se", {"bsc cs", "bsc se"}, FAMILIES) == 1


def test_same_family_gives_point_six():
    assert program_relevance("bsc se", {"bsc it"}, FAMILIES) == Fraction(3, 5)


def test_open_to_all_gives_half():
    assert program_relevance("bsc nursing", set(), FAMILIES) == Fraction(1, 2)


def test_unrelated_program_gives_zero():
    assert program_relevance("bsc nursing", {"bsc it"}, FAMILIES) == 0


def test_program_missing_from_family_table_is_not_a_family_match():
    assert program_relevance("bsc unknown", {"bsc it"}, FAMILIES) == 0
