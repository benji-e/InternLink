"""Job alerts: saved searches that email students about new internships.

A student saves the filters of an internship search. Once a day the alert job
(/api/cron/job-alerts) finds internships posted since the last check that
match, and sends each student one email listing them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Callable
from urllib.parse import urlencode

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import public
from .service import StudentError

MAX_ALERTS = 10
MAX_PER_EMAIL = 10
# Filters an alert may keep: the same names as the search page URL.
ALLOWED = {"q", "location", "sector", "remote", "duration", "my_programme"}
DURATIONS = {"short": (None, "8"), "mid": ("9", "16"), "long": ("17", None)}
DURATION_LABELS = {"short": "up to 8 weeks", "mid": "9–16 weeks", "long": "17+ weeks"}


def _clean_filters(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise StudentError(422, "INVALID_INPUT", "Choose some search filters first.")
    filters: dict[str, str] = {}
    for key, value in raw.items():
        if key not in ALLOWED or value in (None, "", False):
            continue
        text = str(value).strip()[:120]
        if text:
            filters[key] = text
    if filters.get("remote") not in (None, "true", "false"):
        raise StudentError(422, "INVALID_FILTER", "Check the remote filter.")
    if filters.get("duration") not in (None, *DURATIONS):
        raise StudentError(422, "INVALID_FILTER", "Check the duration filter.")
    if filters.get("my_programme") not in (None, "true"):
        filters.pop("my_programme", None)
    return filters


def describe(filters: dict[str, str]) -> str:
    """Plain words for an alert, e.g. "“data” in Kampala, remote"."""
    parts = []
    if filters.get("q"):
        parts.append(f"“{filters['q']}”")
    if filters.get("sector"):
        parts.append(filters["sector"])
    if filters.get("location"):
        parts.append(f"in {filters['location']}")
    if filters.get("remote") == "true":
        parts.append("remote")
    elif filters.get("remote") == "false":
        parts.append("on site")
    if filters.get("duration"):
        parts.append(DURATION_LABELS[filters["duration"]])
    if filters.get("my_programme"):
        parts.append("open to my programme")
    return ", ".join(parts) if parts else "All new internships"


def search_filters(filters: dict[str, str]) -> dict[str, str]:
    """Turn alert filters into search_opportunities() filters."""
    result = {key: value for key, value in filters.items() if key != "duration"}
    low, high = DURATIONS.get(filters.get("duration", ""), (None, None))
    if low:
        result["min_weeks"] = low
    if high:
        result["max_weeks"] = high
    return result


def create_alert(conn, student_id: int, raw_filters: object) -> dict:
    filters = _clean_filters(raw_filters)
    public.search_opportunities(conn, search_filters(filters), student_id)  # rejects bad filters
    with conn.cursor(row_factory=dict_row) as cur:
        count = cur.execute("SELECT count(*) AS n FROM job_alerts WHERE student_id = %s", (student_id,)).fetchone()["n"]
        existing = cur.execute(
            "SELECT alert_id FROM job_alerts WHERE student_id = %s AND filters = %s",
            (student_id, Jsonb(filters)),
        ).fetchone()
        if existing:
            return {"alert": _one(cur, existing["alert_id"]), "created": False}
        if count >= MAX_ALERTS:
            raise StudentError(409, "TOO_MANY_ALERTS", f"You can have up to {MAX_ALERTS} job alerts. Remove one first.")
        row = cur.execute(
            "INSERT INTO job_alerts (student_id, filters, label) VALUES (%s, %s, %s) RETURNING alert_id",
            (student_id, Jsonb(filters), describe(filters)),
        ).fetchone()
        return {"alert": _one(cur, row["alert_id"]), "created": True}


def _one(cur, alert_id: int) -> dict:
    return cur.execute(
        "SELECT alert_id, filters, label, created_at, last_sent_at FROM job_alerts WHERE alert_id = %s",
        (alert_id,),
    ).fetchone()


def list_alerts(conn, student_id: int) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            "SELECT alert_id, filters, label, created_at, last_sent_at FROM job_alerts WHERE student_id = %s ORDER BY created_at",
            (student_id,),
        ).fetchall()


def delete_alert(conn, student_id: int, alert_id: int) -> dict:
    removed = conn.execute("DELETE FROM job_alerts WHERE alert_id = %s AND student_id = %s", (alert_id, student_id)).rowcount
    if not removed:
        raise StudentError(404, "ALERT_NOT_FOUND", "Job alert not found.")
    return {"alert_id": alert_id, "deleted": True}


def _email_html(name: str, groups: list[tuple[dict, list[dict]]], site_url: str) -> str:
    sections = []
    for alert, listings in groups:
        query = urlencode(alert["filters"])
        items = "".join(
            f'<li><a href="{escape(site_url)}/internships/{item["listing_id"]}">{escape(item["title"])}</a>'
            f' · {escape(item["company_name"])} · {"Remote" if item["is_remote"] else escape(item["location"])}'
            f' · closes {item["application_deadline"]:%d %b}</li>'
            for item in listings
        )
        sections.append(
            f'<h3 style="margin-bottom:4px">{escape(alert["label"])}</h3><ul>{items}</ul>'
            f'<p><a href="{escape(site_url)}/internships?{escape(query)}">See all matches</a></p>'
        )
    return (
        f"<p>Hello {escape(name)},</p><p>New internships match your job alerts:</p>{''.join(sections)}"
        f'<p style="color:#666">You can remove alerts from your <a href="{escape(site_url)}/dashboard?page=saved">Saved page</a>.</p>'
    )


def run_alerts(conn, send_email: Callable[[str, str, str], None], site_url: str) -> dict:
    """Email every student whose alerts have new matches. Safe to run repeatedly.

    An alert only moves its "last checked" time forward once the student's
    email has been sent, so a failed email is retried on the next run.
    """
    started = datetime.now(timezone.utc)
    with conn.cursor(row_factory=dict_row) as cur:
        alerts = cur.execute(
            """
            SELECT ja.alert_id, ja.student_id, ja.filters, ja.label, ja.last_checked_at,
                   u.email, u.full_name, u.user_id
            FROM job_alerts ja
            JOIN student_profiles sp ON sp.student_id = ja.student_id
            JOIN users u ON u.user_id = sp.user_id
            WHERE u.status = 'active'
            ORDER BY ja.student_id, ja.alert_id
            """
        ).fetchall()
    by_student: dict[int, list[dict]] = {}
    for alert in alerts:
        by_student.setdefault(alert["student_id"], []).append(alert)

    summary = {"students": 0, "emails": 0, "failed": 0}
    for student_id, student_alerts in by_student.items():
        summary["students"] += 1
        groups = []
        seen: set[int] = set()
        for alert in student_alerts:
            result = public.search_opportunities(
                conn, {**search_filters(alert["filters"]), "page_size": str(MAX_PER_EMAIL), "sort": "newest"},
                student_id, posted_after=alert["last_checked_at"],
            )
            fresh = [item for item in result["results"] if item["listing_id"] not in seen and not item.get("application_status")]
            seen.update(item["listing_id"] for item in fresh)
            if fresh:
                groups.append((alert, fresh))
        ids = [alert["alert_id"] for alert in student_alerts]
        if groups:
            first = student_alerts[0]
            total = sum(len(listings) for _, listings in groups)
            try:
                send_email(first["email"], f"{total} new internship{'s' if total != 1 else ''} for you on InternLink",
                           _email_html(first["full_name"], groups, site_url))
            except Exception:  # noqa: BLE001 - one bad address must not stop the others
                summary["failed"] += 1
                continue
            summary["emails"] += 1
            with conn.transaction():
                conn.execute(
                    "INSERT INTO notifications (user_id, type, title, message, related_type, channel) "
                    "VALUES (%s, 'system', 'New internships for your job alerts', %s, 'job_alerts', 'in_app')",
                    (first["user_id"], f"{total} new internship{'s' if total != 1 else ''} match your job alerts."),
                )
                conn.execute("UPDATE job_alerts SET last_checked_at = %s, last_sent_at = %s WHERE alert_id = ANY(%s)", (started, started, ids))
        else:
            with conn.transaction():
                conn.execute("UPDATE job_alerts SET last_checked_at = %s WHERE alert_id = ANY(%s)", (started, ids))
    return summary
