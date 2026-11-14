"""Company directory, company pages, logos and "suggest a company".

Only verified companies are public. A company appears in the directory even
when it has no open internships, so searching a registered company always
finds it.
"""

from __future__ import annotations

from typing import Any

from psycopg.rows import dict_row

from .service import EMAIL_RE, StudentError

MAX_LOGO_BYTES = 1024 * 1024
PAGE_SIZE = 24


def detect_image(data: bytes) -> str:
    """The image type from its first bytes. SVG is refused: logos are public."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise StudentError(415, "UNSUPPORTED_IMAGE", "Upload the logo as a PNG, JPG or WebP image.")


def save_logo(conn, company_id: int, data: bytes) -> dict:
    if not data:
        raise StudentError(422, "EMPTY_IMAGE", "That file is empty.")
    if len(data) > MAX_LOGO_BYTES:
        raise StudentError(413, "IMAGE_TOO_LARGE", "The logo must be 1 MB or smaller.")
    content_type = detect_image(data)
    conn.execute(
        """
        INSERT INTO company_logos (company_id, content_type, size_bytes, data) VALUES (%s, %s, %s, %s)
        ON CONFLICT (company_id) DO UPDATE SET content_type = EXCLUDED.content_type,
            size_bytes = EXCLUDED.size_bytes, data = EXCLUDED.data, updated_at = now()
        """,
        (company_id, content_type, len(data), data),
    )
    return {"has_logo": True}


def delete_logo(conn, company_id: int) -> dict:
    conn.execute("DELETE FROM company_logos WHERE company_id = %s", (company_id,))
    return {"has_logo": False}


def read_logo(conn, company_id: int) -> dict:
    """A verified company's logo, for anyone to see."""
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            """
            SELECT l.content_type, l.data, l.updated_at FROM company_logos l
            JOIN companies c ON c.company_id = l.company_id
            WHERE l.company_id = %s AND c.verification_status = 'verified'
            """,
            (company_id,),
        ).fetchone()
    if row is None:
        raise StudentError(404, "LOGO_NOT_FOUND", "No logo.")
    return row


def own_logo_info(conn, company_id: int) -> dict:
    """For the employer's own page, whether or not the company is verified yet."""
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            "SELECT content_type, size_bytes, updated_at FROM company_logos WHERE company_id = %s", (company_id,)
        ).fetchone()
    return {"logo": row}


def read_own_logo(conn, company_id: int) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute("SELECT content_type, data, updated_at FROM company_logos WHERE company_id = %s", (company_id,)).fetchone()
    if row is None:
        raise StudentError(404, "LOGO_NOT_FOUND", "No logo yet.")
    return row


def list_companies(conn, filters: dict[str, str]) -> dict:
    query = (filters.get("q") or "").strip()[:120]
    sector = (filters.get("sector") or "").strip()[:80]
    try:
        page = max(1, int(filters.get("page") or 1))
    except ValueError:
        raise StudentError(422, "INVALID_FILTER", "Check the page number.") from None
    clauses = ["c.verification_status = 'verified'"]
    params: list[Any] = []
    if query:
        clauses.append("(c.name ILIKE %s OR c.sector ILIKE %s OR c.description ILIKE %s)")
        params += [f"%{query}%"] * 3
    if sector:
        clauses.append("c.sector ILIKE %s")
        params.append(sector)
    where = " AND ".join(clauses)
    with conn.cursor(row_factory=dict_row) as cur:
        total = cur.execute(f"SELECT count(*) AS n FROM companies c WHERE {where}", params).fetchone()["n"]
        rows = cur.execute(
            f"""
            SELECT c.company_id, c.name, c.sector, c.location, c.description,
                   EXISTS (SELECT 1 FROM company_logos l WHERE l.company_id = c.company_id) AS has_logo,
                   o.open_internships
            FROM companies c
            CROSS JOIN LATERAL (
                SELECT count(*) AS open_internships FROM v_open_listings v WHERE v.company_id = c.company_id
            ) o
            WHERE {where}
            -- Companies hiring now come first.
            ORDER BY o.open_internships > 0 DESC, lower(c.name)
            LIMIT %s OFFSET %s
            """,
            [*params, PAGE_SIZE, (page - 1) * PAGE_SIZE],
        ).fetchall()
        sectors = cur.execute(
            "SELECT sector AS name, count(*) AS count FROM companies WHERE verification_status = 'verified' "
            "GROUP BY sector ORDER BY count(*) DESC, sector"
        ).fetchall()
    return {"companies": rows, "count": int(total), "page": page, "page_size": PAGE_SIZE, "sectors": sectors}


def company_profile(conn, company_id: int) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        company = cur.execute(
            """
            SELECT c.company_id, c.name, c.sector, c.location, c.description, c.website, c.verified_at,
                   EXISTS (SELECT 1 FROM company_logos l WHERE l.company_id = c.company_id) AS has_logo
            FROM companies c WHERE c.company_id = %s AND c.verification_status = 'verified'
            """,
            (company_id,),
        ).fetchone()
        if company is None:
            raise StudentError(404, "COMPANY_NOT_FOUND", "This company isn't on InternLink.")
        company["open_internships"] = cur.execute(
            """
            SELECT v.listing_id, v.title, v.sector, v.location, v.is_remote, v.duration_weeks,
                   v.slots_remaining, v.application_deadline, v.required_skills
            FROM v_open_listings v WHERE v.company_id = %s ORDER BY v.application_deadline
            """,
            (company_id,),
        ).fetchall()
        company["past_internships"] = cur.execute(
            """
            SELECT count(*) AS n FROM listings l
            WHERE l.company_id = %s AND l.posted_at IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM v_open_listings v WHERE v.listing_id = l.listing_id)
            """,
            (company_id,),
        ).fetchone()["n"]
        company["interns_placed"] = cur.execute(
            """
            SELECT count(*) AS n FROM placements p JOIN applications a ON a.application_id = p.application_id
            JOIN listings l ON l.listing_id = a.listing_id
            WHERE l.company_id = %s AND p.status IN ('confirmed', 'completed')
            """,
            (company_id,),
        ).fetchone()["n"]
    return company


def request_company(conn, payload: dict) -> dict:
    """A student suggests a company that isn't on InternLink yet."""
    name = payload.get("company_name")
    if not isinstance(name, str) or not name.strip():
        raise StudentError(422, "INVALID_INPUT", "Enter the company's name.")
    name = " ".join(name.split())
    if len(name) > 160:
        raise StudentError(422, "INVALID_INPUT", "The company name is too long.")
    website = payload.get("website")
    website = website.strip()[:300] if isinstance(website, str) and website.strip() else None
    email = payload.get("requester_email")
    email = email.strip().lower() if isinstance(email, str) else ""
    if not email or len(email) > 254 or not EMAIL_RE.fullmatch(email):
        raise StudentError(422, "INVALID_EMAIL", "Enter your email so we can tell you when they join.")
    with conn.cursor(row_factory=dict_row) as cur:
        listed = cur.execute(
            "SELECT company_id FROM companies WHERE lower(name) = lower(%s) AND verification_status = 'verified'", (name,)
        ).fetchone()
        if listed:
            raise StudentError(409, "ALREADY_LISTED", f"{name} is already on InternLink.")
        cur.execute(
            """
            INSERT INTO company_requests (company_name, website, requester_email) VALUES (%s, %s, %s)
            ON CONFLICT (lower(company_name), requester_email) DO NOTHING
            """,
            (name, website, email),
        )
    return {"message": f"Thanks. We'll invite {name} and email you when they join InternLink."}


def company_requests(conn) -> list[dict]:
    """Open suggestions grouped by company name, most requested first."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """
            SELECT min(company_name) AS company_name, count(*) AS requests,
                   array_remove(array_agg(DISTINCT website), NULL) AS websites,
                   max(created_at) AS last_requested_at
            FROM company_requests WHERE status = 'open'
            GROUP BY lower(company_name)
            ORDER BY count(*) DESC, max(created_at) DESC
            """
        ).fetchall()


def close_company_request(conn, payload: dict) -> dict:
    name = payload.get("company_name")
    status = payload.get("status")
    if not isinstance(name, str) or not name.strip():
        raise StudentError(422, "INVALID_INPUT", "Choose a suggestion.")
    if status not in ("invited", "declined"):
        raise StudentError(422, "INVALID_INPUT", "Mark the suggestion as invited or declined.")
    updated = conn.execute(
        "UPDATE company_requests SET status = %s WHERE lower(company_name) = lower(%s) AND status = 'open'",
        (status, name.strip()),
    ).rowcount
    if not updated:
        raise StudentError(404, "NOT_FOUND", "No open suggestions for that company.")
    return {"company_name": name.strip(), "status": status, "updated": updated}
