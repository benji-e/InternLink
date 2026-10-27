# InternLink Uganda

Centralized internship placement and intelligent matching platform
(MUST, Faculty of Computing and Informatics, Software Project Management, Group 13).

## Matching engine (WBS 4.6)

Design: [docs/design/3.4-matching-algorithm-design.md](docs/design/3.4-matching-algorithm-design.md)

| File | What it does |
|---|---|
| `matching_engine/scoring.py` | `score(student, opportunity)` → 0–100 score, breakdown, matched/missing skills |
| `matching_engine/config.py` | Weights (0.45 / 0.35 / 0.20), `MIN_SCORE`, top-K, timeouts |
| `matching_engine/normalize.py` | Cleans free-text skills/interests (e.g. `JS` → `javascript`) |
| `matching_engine/models.py` | `StudentProfile`, `Opportunity`, `MatchResult` |

### Run the tests

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements-dev.txt
pytest
```

The engine has no database or web code, so it can be tested on its own (NFR08).
