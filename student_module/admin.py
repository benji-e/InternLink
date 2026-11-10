"""Extra detail for the admin's organisation request screens."""

from __future__ import annotations

from urllib.parse import urlsplit

from psycopg.rows import dict_row

from .service import StudentError


def _domain(value: str | None) -> str | None:
    if not value:
        return None
    host = urlsplit(value if "//" in value else f"//{value}").hostname or ""
    return host.lower().removeprefix("www.") or None


def registration_detail(conn, org_type: str, org_id: int) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        if org_type == "company":
            company = cur.execute(
                """
                SELECT company_id AS org_id, name, sector, location, description, contact_email, website,
                       verification_status AS status, rejection_reason, created_at
                FROM companies WHERE company_id = %s
                """,
                (org_id,),
            ).fetchone()
            if company is None:
                raise StudentError(404, "NOT_FOUND", "Company not found.")
            company["people"] = cur.execute(
                """
                SELECT full_name, email, phone, status, (email_verified_at IS NOT NULL) AS email_confirmed
                FROM users WHERE company_id = %s ORDER BY created_at
                """,
                (org_id,),
            ).fetchall()
            company["draft_listings"] = cur.execute(
                "SELECT count(*) AS n FROM listings WHERE company_id = %s AND status = 'draft'", (org_id,)
            ).fetchone()["n"]
            # Does the people's email domain match the company website? A quick trust signal.
            website = _domain(company["website"])
            emails = {person["email"].rsplit("@", 1)[-1].lower() for person in company["people"]}
            company["email_matches_website"] = None if not website else any(
                domain == website or domain.endswith(f".{website}") for domain in emails
            )
            company["org_type"] = "company"
            return company
        if org_type == "university":
            university = cur.execute(
                """
                SELECT university_id AS org_id, name, location, email_domain, status, rejection_reason, created_at
                FROM universities WHERE university_id = %s
                """,
                (org_id,),
            ).fetchone()
            if university is None:
                raise StudentError(404, "NOT_FOUND", "University not found.")
            university["people"] = cur.execute(
                """
                SELECT full_name, email, phone, status, (email_verified_at IS NOT NULL) AS email_confirmed
                FROM users WHERE university_id = %s AND role = 'coordinator' ORDER BY created_at
                """,
                (org_id,),
            ).fetchall()
            university["student_requests"] = cur.execute(
                "SELECT count(*) AS n FROM university_requests WHERE lower(university_name) = lower(%s)",
                (university["name"],),
            ).fetchone()["n"]
            university["org_type"] = "university"
            return university
    raise StudentError(404, "NOT_FOUND", "Unknown organisation type.")


def university_requests(conn) -> list[dict]:
    """Open student requests grouped by university name, most requested first."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """
            SELECT min(university_name) AS university_name, count(*) AS requests,
                   min(created_at) AS first_requested_at, max(created_at) AS last_requested_at,
                   array_remove(array_agg(DISTINCT coordinator_email), NULL) AS coordinator_emails
            FROM university_requests
            WHERE status = 'open'
            GROUP BY lower(university_name)
            ORDER BY count(*) DESC, min(created_at)
            """
        ).fetchall()


def close_university_request(conn, payload: dict) -> dict:
    name = payload.get("university_name")
    status = payload.get("status")
    if not isinstance(name, str) or not name.strip():
        raise StudentError(422, "INVALID_INPUT", "Choose a request.")
    if status not in ("added", "declined"):
        raise StudentError(422, "INVALID_INPUT", "Mark the request as added or declined.")
    updated = conn.execute(
        "UPDATE university_requests SET status = %s WHERE lower(university_name) = lower(%s) AND status = 'open'",
        (status, name.strip()),
    ).rowcount
    if not updated:
        raise StudentError(404, "NOT_FOUND", "No open requests for that university.")
    return {"university_name": name.strip(), "status": status, "updated": updated}
