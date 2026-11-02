"""NFR01 load test (WBS 4.6.3): 200 concurrent students, p95 must be under 5 s.

Each virtual student logs in as a different seeded student and requests
recommendations through the real HTTP endpoint in a loop for the given time.

Usage (API already running, e.g. `uvicorn matching_engine.api:app --port 8765`):
    python scripts/load_test.py --url http://localhost:8765 --dsn <load database> \
        --secret <JWT secret> --users 200 --seconds 300 --report docs/testing/results/nfr01.md
"""
import argparse
import asyncio
import random
import statistics
import time
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import psycopg

PATH = "/api/v1/students/me/recommendations"


def student_user_ids(dsn: str, count: int) -> list[int]:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            """SELECT sp.user_id FROM student_profiles sp
               WHERE EXISTS (SELECT 1 FROM student_skills ss WHERE ss.student_id = sp.student_id)
               ORDER BY sp.student_id LIMIT %s""", (count,)).fetchall()
    if len(rows) < count:
        raise SystemExit(f"Only {len(rows)} students with skills; need {count}")
    return [r[0] for r in rows]


def make_token(user_id: int, secret: str, hours: int = 2) -> str:
    claims = {"sub": str(user_id), "role": "student", "exp": datetime.now(timezone.utc) + timedelta(hours=hours)}
    return jwt.encode(claims, secret, algorithm="HS256")


async def virtual_student(client, token, stop_at, latencies, statuses, think, rng):
    headers = {"Authorization": f"Bearer {token}"}
    if think:  # spread the start so 200 students don't all click in the same instant
        await asyncio.sleep(rng.uniform(0, 2 * think))
    while time.perf_counter() < stop_at:
        start = time.perf_counter()
        try:
            response = await client.get(PATH, headers=headers)
            statuses[response.status_code] = statuses.get(response.status_code, 0) + 1
        except httpx.HTTPError as exc:
            statuses[type(exc).__name__] = statuses.get(type(exc).__name__, 0) + 1
        latencies.append(time.perf_counter() - start)
        if think:  # the student reads the list before clicking again
            await asyncio.sleep(rng.uniform(0.5 * think, 1.5 * think))


def percentile(values, p):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * len(ordered) + 0.5)) - 1)]


async def run(args):
    tokens = [make_token(uid, args.secret) for uid in student_user_ids(args.dsn, args.users)]
    latencies: list[float] = []
    statuses: dict = {}
    limits = httpx.Limits(max_connections=args.users, max_keepalive_connections=args.users)
    async with httpx.AsyncClient(base_url=args.url, timeout=30, limits=limits) as client:
        started = time.perf_counter()
        stop_at = started + args.seconds
        rng = random.Random(42)
        await asyncio.gather(*(virtual_student(client, t, stop_at, latencies, statuses, args.think, rng)
                               for t in tokens))
        elapsed = time.perf_counter() - started
    return latencies, statuses, elapsed


def report(args, latencies, statuses, elapsed) -> str:
    ok = statuses.get(200, 0)
    total = len(latencies)
    p95 = percentile(latencies, 95)
    passed = p95 < 5.0 and ok == total
    return "\n".join([
        "# NFR01 load test result",
        "",
        f"- **Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- **Target:** `GET {PATH}` at {args.url}",
        f"- **Virtual students:** {args.users} at the same time, each a different seeded student",
        f"- **Think time between a student's requests:** "
        + (f"{0.5 * args.think:.1f}–{1.5 * args.think:.1f} s (average {args.think:g} s)" if args.think
           else "none (stress test: every student re-requests immediately)"),
        f"- **Duration:** {elapsed:.0f} s",
        f"- **Requests:** {total} ({total / elapsed:.1f} per second)",
        f"- **Responses:** {', '.join(f'{k}: {v}' for k, v in sorted(statuses.items(), key=str))}",
        "",
        "| Statistic | Seconds |",
        "|---|---|",
        f"| Minimum | {min(latencies):.3f} |",
        f"| Median | {statistics.median(latencies):.3f} |",
        f"| 95th percentile | **{p95:.3f}** |",
        f"| Maximum | {max(latencies):.3f} |",
        "",
        f"**NFR01 (95% under 5 s at {args.users} concurrent students): {'PASS' if passed else 'FAIL'}**",
        "",
    ])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True)
    parser.add_argument("--dsn", required=True, help="database the API uses, to pick student accounts")
    parser.add_argument("--secret", required=True, help="JWT secret the API checks tokens with")
    parser.add_argument("--users", type=int, default=200)
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("--think", type=float, default=0,
                        help="average seconds a student waits between requests (0 = stress test)")
    parser.add_argument("--report", help="write the result as Markdown to this file")
    args = parser.parse_args()

    latencies, statuses, elapsed = asyncio.run(run(args))
    text = report(args, latencies, statuses, elapsed)
    print(text)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(text)


if __name__ == "__main__":
    main()
