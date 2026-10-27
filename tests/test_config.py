"""Section 5.8: weights live in one config and must add up to 1.0."""
from fractions import Fraction

import pytest

from matching_engine.config import DEFAULT_CONFIG, MatchingConfig


def test_default_weights_match_the_design():
    assert DEFAULT_CONFIG.w_skill == Fraction("0.45")
    assert DEFAULT_CONFIG.w_prog == Fraction("0.35")
    assert DEFAULT_CONFIG.w_int == Fraction("0.20")
    assert DEFAULT_CONFIG.min_score == 20
    assert DEFAULT_CONFIG.algorithm_version == "v1"


def test_weights_that_do_not_add_up_to_one_are_rejected():
    with pytest.raises(ValueError, match="add up to 1"):
        MatchingConfig(w_skill="0.5", w_prog="0.35", w_int="0.20")


def test_negative_weight_is_rejected():
    with pytest.raises(ValueError, match="negative"):
        MatchingConfig(w_skill="1.2", w_prog="-0.4", w_int="0.2")
