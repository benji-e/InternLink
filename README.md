# InternLink Uganda

Centralized internship placement and intelligent matching platform
(MUST, Faculty of Computing and Informatics, Software Project Management, Group 13).

## Matching engine (WBS 4.6)

Design: [docs/design/3.4-matching-algorithm-design.md](docs/design/3.4-matching-algorithm-design.md)

Scoring and ranking are done by the database function `fn_recommendations`
(PR #2, `03_views_functions.sql`). The Python package wraps it for the API.

| File | What it does |
|---|---|
| `matching_engine/service.py` | `recommend_for_student(conn, student_id, k=10)` → ranked results with breakdown, `applied` flag and matched/missing skills; raises `ProfileIncomplete` (422) or `MatchingUnavailable` (503) |
| `matching_engine/config.py` | Default/maximum list size and the 4 s time limit |

### Run the tests

The tests need PostgreSQL 16 with PR #2's `01_schema.sql`, `02_functions_triggers.sql`,
`03_views_functions.sql` and `05_seed.sql` loaded (in that order). Then:

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements-dev.txt
set INTERNLINK_TEST_DSN=postgresql://postgres@localhost:5432/internlink   # macOS/Linux: export ...
pytest
```

Each test runs in a transaction that is rolled back, so the database is left unchanged.
Without `INTERNLINK_TEST_DSN` the tests are skipped.

One test is marked `xfail`: the known SR20 defect in the interest score (design Section 5.1).
