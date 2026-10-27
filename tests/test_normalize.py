"""Section 3.3: clean free-text values before comparing them."""
from matching_engine.normalize import normalize, normalize_all


def test_lowercases_and_trims():
    assert normalize("  Python ") == "python"


def test_collapses_inner_spaces():
    assert normalize("Data   Science") == "data science"


def test_maps_known_synonyms():
    assert normalize("JS") == "javascript"
    assert normalize("ml") == "machine learning"


def test_normalize_all_returns_a_clean_set_without_blanks():
    assert normalize_all(["SQL", "sql ", "", "  "]) == {"sql"}
