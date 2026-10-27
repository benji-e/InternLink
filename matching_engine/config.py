"""Matching-engine settings (design Section 5.8).

Changing a weight is a change request (WBS Section E.2): bump
`algorithm_version` whenever the weights change, so old scores stay traceable.
"""
from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class MatchingConfig:
    w_skill: Fraction = Fraction("0.45")
    w_prog: Fraction = Fraction("0.35")
    w_int: Fraction = Fraction("0.20")
    min_score: int = 20
    default_k: int = 10
    max_k: int = 50
    cache_ttl_seconds: int = 600
    timeout_seconds: float = 4.0
    algorithm_version: str = "v1"

    def __post_init__(self):
        # Accept "0.45" strings so weights are exact, never binary floats.
        for name in ("w_skill", "w_prog", "w_int"):
            object.__setattr__(self, name, Fraction(getattr(self, name)))
        weights = (self.w_skill, self.w_prog, self.w_int)
        if any(w < 0 for w in weights):
            raise ValueError("Matching weights cannot be negative")
        if sum(weights) != 1:
            raise ValueError(f"Matching weights must add up to 1.0, got {float(sum(weights))}")


DEFAULT_CONFIG = MatchingConfig()
