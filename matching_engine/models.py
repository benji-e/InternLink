"""Input and output shapes for the engine (design Sections 3 and 5.7).

Field names follow the design for now; align them with Lubega's ERD (WBS 3.2)
when it lands.
"""
from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class StudentProfile:
    program: str
    skills: Sequence[str] = ()
    interests: Sequence[str] = ()
    year_of_study: int | None = None


@dataclass(frozen=True)
class Opportunity:
    sector: str
    target_programs: Sequence[str] = ()  # empty = open to all programs
    required_skills: Sequence[str] = ()
    tags: Sequence[str] = ()


@dataclass(frozen=True)
class MatchResult:
    score: int  # 0-100
    breakdown: dict[str, float] = field(default_factory=dict)
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
