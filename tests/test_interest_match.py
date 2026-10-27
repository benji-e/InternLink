"""Section 5.4: S_int = 0.6 x sector_hit + 0.4 x tag_cover (or sector_hit if no tags)."""
from fractions import Fraction

from matching_engine.scoring import interest_match

INTERESTS = {"fintech", "data science"}


def test_sector_hit_and_half_the_tags_gives_point_eight():
    assert interest_match(INTERESTS, "fintech", {"data science", "banking"}) == Fraction(4, 5)


def test_no_sector_and_no_tag_overlap_gives_zero():
    assert interest_match(INTERESTS, "telecom", {"infrastructure"}) == 0


def test_tags_only_without_sector_hit():
    assert interest_match(INTERESTS, "telecom", {"data science"}) == Fraction(2, 5)


def test_no_tags_uses_sector_hit_only():
    assert interest_match(INTERESTS, "fintech", set()) == 1
    assert interest_match(INTERESTS, "telecom", set()) == 0
