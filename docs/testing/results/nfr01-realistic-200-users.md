# NFR01 load test result

- **Date:** 2026-10-30 02:57
- **Target:** `GET /api/v1/students/me/recommendations` at http://127.0.0.1:8765
- **Virtual students:** 200 at the same time, each a different seeded student
- **Think time between a student's requests:** 5.0–15.0 s (average 10 s)
- **Duration:** 316 s
- **Requests:** 4097 (13.0 per second)
- **Responses:** ReadError: 1, RemoteProtocolError: 13, 200: 4083

| Statistic | Seconds |
|---|---|
| Minimum | 0.057 |
| Median | 1.314 |
| 95th percentile | **20.282** |
| Maximum | 65.160 |

**NFR01 (95% under 5 s at 200 concurrent students): FAIL**
