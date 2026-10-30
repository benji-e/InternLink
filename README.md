# InternLink Uganda

Centralized internship placement and intelligent matching platform
(MUST, Faculty of Computing and Informatics, Software Project Management, Group 13).

## Matching engine (WBS 4.6)

Design: [docs/design/3.4-matching-algorithm-design.md](docs/design/3.4-matching-algorithm-design.md)

| File | What it does |
|---|---|
| `matching_engine/scoring.py` | `score(student, opportunity)` → 0–100 score, breakdown, matched/missing skills |
| `matching_engine/ranking.py` | `recommend(student, listings, today=...)` → filters, scores, sorts and returns the top 10 |
| `matching_engine/config.py` | Weights (0.45 / 0.35 / 0.20), `MIN_SCORE`, top-K, timeouts |
| `matching_engine/normalize.py` | Cleans free-text skills/interests (e.g. `JS` → `javascript`) |
| `matching_engine/models.py` | `StudentProfile`, `Opportunity`, `Listing`, `MatchResult` |
| `matching_engine/db.py` | Loads a student and the eligible listings from the PostgreSQL schema (`v_open_listings`), then calls `recommend()` |

### Run the tests

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements-dev.txt
pytest
```

The scoring and ranking code has no database or web code, so it can be tested on its own (NFR08).

### Database tests (optional)

`tests/test_db_integration.py` runs the engine against the real schema and seed data
(PR #2: `01_schema.sql`, `02_functions_triggers.sql`, `03_views_functions.sql`, `05_seed.sql`).
Load those four files into an empty PostgreSQL 16 database, then:

```bash
set INTERNLINK_TEST_DSN=postgresql://postgres@localhost:5432/internlink   # macOS/Linux: export ...
pytest
```

Without `INTERNLINK_TEST_DSN` these tests are skipped.
