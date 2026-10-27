"""Clean skill/interest/tag values before comparing them (design Section 3.3).

Only needed while any of these are free text. Once the database uses shared
lists (WBS 3.2), this still does no harm.
"""
from collections.abc import Iterable

SYNONYMS = {
    "js": "javascript",
    "ts": "typescript",
    "ml": "machine learning",
    "ai": "artificial intelligence",
    "py": "python",
    "postgres": "postgresql",
    "ms excel": "excel",
}


def normalize(value: str) -> str:
    cleaned = " ".join(value.lower().split())
    return SYNONYMS.get(cleaned, cleaned)


def normalize_all(values: Iterable[str]) -> set[str]:
    return {v for v in (normalize(x) for x in values) if v}
