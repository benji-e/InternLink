"""NFR01 load test (WBS 4.6.3): 200 concurrent students, p95 under 5 s.

Each virtual student logs in as a different seeded student and requests
recommendations through the real HTTP endpoint in a loop for the given time.

Usage (API already running, e.g. `python -m matching_engine.api --port 8765`):
    python scripts/load_test.py --url http://localhost:8765 --dsn <load database> \
        --secret <JWT secret> --users 200 --seconds 300 --report docs/testing/results/nfr01.md
"""
import argparse
import http.client
import random
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

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


def virtual_student(token: str, stop_at: float, think: float, url: tuple, seed: int) -> tuple:
    scheme, host, port, request_path = url
    connection_type = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    connection = connection_type(host, port, timeout=30)
    rng = random.Random(seed)
    latencies = []
    statuses = {}
    if think:
        time.sleep(rng.uniform(0, 2 * think))

    try:
        while time.perf_counter() < stop_at:
            start = time.perf_counter()
            try:
                connection.request(
                    "GET",
                    request_path,
                    headers={"Authorization": f"Bearer {token}"},
                )
                response = connection.getresponse()
                response.read()
                status = response.status
            except (OSError, http.client.HTTPException) as exc:
                status = type(exc).__name__
                connection.close()
                connection = connection_type(host, port, timeout=30)
            statuses[status] = statuses.get(status, 0) + 1
            latencies.append(time.perf_counter() - start)
            if think:
                time.sleep(rng.uniform(0.5 * think, 1.5 * think))
    finally:
        connection.close()

    return latencies, statuses


def percentile(values, p):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * len(ordered) + 0.5)) - 1)]


def run(args):
    tokens = [make_token(uid, args.secret) for uid in student_user_ids(args.dsn, args.users)]
    parsed_url = urlsplit(args.url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
        raise ValueError("--url must be an HTTP or HTTPS URL with a host")
    port = parsed_url.port or (443 if parsed_url.scheme == "https" else 80)
    request_path = f"{parsed_url.path.rstrip('/')}{PATH}"
    if parsed_url.query:
        request_path = f"{request_path}?{parsed_url.query}"
    url = (parsed_url.scheme, parsed_url.hostname, port, request_path)

    started = time.perf_counter()
    stop_at = started + args.seconds
    with ThreadPoolExecutor(max_workers=args.users) as executor:
        futures = [
            executor.submit(virtual_student, token, stop_at, args.think, url, 42 + index)
            for index, token in enumerate(tokens)
        ]
        results = [future.result() for future in futures]
    elapsed = time.perf_counter() - started

    latencies = [latency for student_latencies, _ in results for latency in student_latencies]
    statuses = {}
    for _, student_statuses in results:
        for status, count in student_statuses.items():
            statuses[status] = statuses.get(status, 0) + count
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
    parser.add_argument("--secret", required=True, help="JWT secret the API checks with")
    parser.add_argument("--users", type=int, default=200)
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("--think", type=float, default=0,
                        help="average seconds a student waits between requests (0 = stress test)")
    parser.add_argument("--report", help="write the result as Markdown to this file")
    args = parser.parse_args()

    latencies, statuses, elapsed = run(args)
    text = report(args, latencies, statuses, elapsed)
    print(text)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(text)


if __name__ == "__main__":
    main()
